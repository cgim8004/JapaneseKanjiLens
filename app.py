import json
import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import imageio_ffmpeg
from flask import Flask, jsonify, render_template, request, send_file
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100 MB

BASE_DIR = Path(__file__).resolve().parent
WORK_DIR = Path(os.environ.get('WORK_DIR', BASE_DIR / 'work'))
WORK_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = {'mp3', 'wav', 'm4a', 'aac', 'flac', 'ogg', 'opus', 'webm', 'mp4'}


def allowed(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def ffmpeg_path():
    path = shutil.which('ffmpeg')
    return path or imageio_ffmpeg.get_ffmpeg_exe()


def write_status(job_dir, state, message='', error=''):
    status_path = job_dir / 'status.json'
    status_path.write_text(
        json.dumps({'state': state, 'message': message, 'error': error}, ensure_ascii=False),
        encoding='utf-8'
    )


def process_job(job_id, level):
    job_dir = WORK_DIR / job_id
    input_files = [p for p in job_dir.iterdir() if p.is_file() and p.name not in {'status.json', 'process.log', 'lecture_cleaned.mp3'}]
    if not input_files:
        write_status(job_dir, 'error', error='업로드된 파일을 찾을 수 없습니다.')
        return

    input_path = input_files[0]
    output_path = job_dir / 'lecture_cleaned.mp3'

    try:
        ffmpeg = ffmpeg_path()
        settings = {
            'light': ('100', '1.4', '0.65'),
            'medium': ('130', '1.7', '0.75'),
            'strong': ('170', '2.0', '0.85'),
        }
        highpass_hz, comp_ratio, denoise = settings.get(level, settings['medium'])

        # Keep the filter chain reasonably light for Render's free 512 MB instance.
        filters = (
            f'highpass=f={highpass_hz}:p=2,'
            f'afftdn=nr={denoise}:nf=-40,'
            f'acompressor=threshold=0.08:ratio={comp_ratio}:attack=15:release=180:makeup=2,'
            'loudnorm=I=-16:TP=-1.5:LRA=11'
        )

        cmd = [
            ffmpeg, '-hide_banner', '-loglevel', 'error', '-y',
            '-i', str(input_path),
            '-vn', '-af', filters,
            '-ar', '44100', '-ac', '1',
            '-c:a', 'libmp3lame', '-b:a', '128k', str(output_path)
        ]

        write_status(job_dir, 'processing', '음성을 복원하고 있습니다. 녹음 길이에 따라 시간이 걸릴 수 있습니다.')
        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=60 * 60 * 6)
        if completed.returncode != 0 or not output_path.exists():
            detail = completed.stderr.strip()[-1200:]
            write_status(job_dir, 'error', error=f'음성 처리에 실패했습니다. {detail}')
            return

        try:
            input_path.unlink()
        except OSError:
            pass
        write_status(job_dir, 'done', '복원이 완료되었습니다.')
    except subprocess.TimeoutExpired:
        write_status(job_dir, 'error', error='처리 시간이 너무 오래 걸려 중단되었습니다.')
    except Exception as exc:
        write_status(job_dir, 'error', error=f'처리 중 오류가 발생했습니다: {exc}')


@app.get('/')
def index():
    return render_template('index.html')


@app.post('/api/process')
def process_audio():
    try:
        # Resolve once here so an unavailable bundled FFmpeg is reported before upload work begins.
        ffmpeg_path()
    except Exception as exc:
        return jsonify(error=f'FFmpeg를 준비하지 못했습니다: {exc}'), 500

    uploaded = request.files.get('audio')
    if not uploaded or not uploaded.filename:
        return jsonify(error='음성 파일을 선택해주세요.'), 400
    if not allowed(uploaded.filename):
        return jsonify(error='지원하지 않는 파일 형식입니다.'), 400

    job_id = uuid.uuid4().hex
    job_dir = WORK_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    input_path = job_dir / secure_filename(uploaded.filename)

    try:
        write_status(job_dir, 'uploading', '파일을 서버에 업로드하고 있습니다.')
        uploaded.save(input_path)

        level = request.form.get('level', 'medium')
        write_status(job_dir, 'queued', '업로드 완료. 음성 복원을 시작합니다.')

        log_path = job_dir / 'process.log'
        log_file = log_path.open('w', encoding='utf-8')
        try:
            subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve()), '--worker', job_id, level],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except Exception:
            log_file.close()
            raise
        log_file.close()

        return jsonify(ok=True, job_id=job_id, status_url=f'/api/status/{job_id}')
    except Exception as exc:
        write_status(job_dir, 'error', error=f'업로드/처리 시작 중 오류가 발생했습니다: {exc}')
        return jsonify(error=f'업로드/처리 시작 중 오류가 발생했습니다: {exc}'), 500


@app.get('/api/status/<job_id>')
def status(job_id):
    if '/' in job_id or '\\' in job_id or not job_id.isalnum():
        return jsonify(error='잘못된 요청입니다.'), 400
    job_dir = WORK_DIR / job_id
    status_path = job_dir / 'status.json'
    if not status_path.exists():
        return jsonify(error='작업을 찾을 수 없습니다.'), 404
    try:
        data = json.loads(status_path.read_text(encoding='utf-8'))
    except Exception:
        return jsonify(error='작업 상태를 읽을 수 없습니다.'), 500
    if data.get('state') == 'done':
        data['download_url'] = f'/api/download/{job_id}'
        data['filename'] = 'lecture_cleaned.mp3'
    return jsonify(data)


@app.get('/api/download/<job_id>')
def download(job_id):
    if '/' in job_id or '\\' in job_id or not job_id.isalnum():
        return jsonify(error='잘못된 요청입니다.'), 400
    output_path = WORK_DIR / job_id / 'lecture_cleaned.mp3'
    if not output_path.exists():
        return jsonify(error='처리된 파일을 찾을 수 없습니다.'), 404
    return send_file(output_path, as_attachment=True, download_name='lecture_cleaned.mp3')


@app.errorhandler(413)
def too_large(_):
    return jsonify(error='파일이 너무 큽니다. 최대 100MB까지 지원합니다.'), 413


if __name__ == '__main__':
    if len(sys.argv) >= 3 and sys.argv[1] == '--worker':
        process_job(sys.argv[2], sys.argv[3] if len(sys.argv) >= 4 else 'medium')
    else:
        app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)
