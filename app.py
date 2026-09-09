import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024 * 1024  # 2 GB

BASE_DIR = Path(__file__).resolve().parent
WORK_DIR = BASE_DIR / 'work'
WORK_DIR.mkdir(exist_ok=True)

ALLOWED_EXTENSIONS = {'mp3', 'wav', 'm4a', 'aac', 'flac', 'ogg', 'opus', 'webm', 'mp4'}


def allowed(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def ffmpeg_exists():
    return shutil.which('ffmpeg') is not None


@app.get('/')
def index():
    return render_template('index.html')


@app.post('/api/process')
def process_audio():
    if not ffmpeg_exists():
        return jsonify(error='FFmpeg가 서버에 설치되어 있지 않습니다.'), 500

    uploaded = request.files.get('audio')
    if not uploaded or not uploaded.filename:
        return jsonify(error='음성 파일을 선택해주세요.'), 400
    if not allowed(uploaded.filename):
        return jsonify(error='지원하지 않는 파일 형식입니다.'), 400

    job_id = uuid.uuid4().hex
    job_dir = WORK_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    input_path = job_dir / secure_filename(uploaded.filename)
    output_path = job_dir / 'lecture_cleaned.wav'

    try:
        # save() streams the multipart body to disk instead of holding the entire recording in RAM
        uploaded.save(input_path)

        level = request.form.get('level', 'medium')
        settings = {
            'light': ('100', '1.4', '0.65'),
            'medium': ('130', '1.7', '0.75'),
            'strong': ('170', '2.0', '0.85'),
        }
        highpass_hz, comp_ratio, denoise = settings.get(level, settings['medium'])

        # Designed for lecture recordings: cut desk/pen thumps, reduce steady noise,
        # compress speech dynamics, then normalize overall loudness.
        filters = (
            f'highpass=f={highpass_hz}:p=2,'
            f'afftdn=nr={denoise}:nf=-40,'
            f'acompressor=threshold=0.08:ratio={comp_ratio}:attack=15:release=180:makeup=2,'
            'dynaudnorm=f=150:g=15:p=0.9:m=10,'
            'loudnorm=I=-16:TP=-1.5:LRA=11'
        )

        cmd = [
            'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
            '-i', str(input_path),
            '-vn', '-af', filters,
            '-ar', '48000', '-ac', '2',
            '-c:a', 'pcm_s16le', str(output_path)
        ]
        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=60 * 60 * 6)
        if completed.returncode != 0 or not output_path.exists():
            detail = completed.stderr.strip()[-1000:]
            return jsonify(error=f'음성 처리에 실패했습니다. {detail}'), 500

        return jsonify(
            ok=True,
            download_url=f'/api/download/{job_id}',
            filename='lecture_cleaned.wav'
        )
    except subprocess.TimeoutExpired:
        return jsonify(error='처리 시간이 너무 오래 걸려 중단되었습니다.'), 504
    except Exception as exc:
        return jsonify(error=f'처리 중 오류가 발생했습니다: {exc}'), 500
    finally:
        # Keep output for download; remove only the original after successful processing.
        if output_path.exists() and input_path.exists():
            try:
                input_path.unlink()
            except OSError:
                pass


@app.get('/api/download/<job_id>')
def download(job_id):
    if '/' in job_id or '\\' in job_id or not job_id.isalnum():
        return jsonify(error='잘못된 요청입니다.'), 400
    output_path = WORK_DIR / job_id / 'lecture_cleaned.wav'
    if not output_path.exists():
        return jsonify(error='처리된 파일을 찾을 수 없습니다.'), 404
    return send_file(output_path, as_attachment=True, download_name='lecture_cleaned.wav')


@app.errorhandler(413)
def too_large(_):
    return jsonify(error='파일이 너무 큽니다. 최대 2GB까지 지원합니다.'), 413


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)
