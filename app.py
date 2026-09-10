import json
import os
import shutil
import subprocess
import threading
import uuid
from pathlib import Path

import imageio_ffmpeg
from flask import Flask, jsonify, render_template, request, send_file
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024

BASE_DIR = Path(__file__).resolve().parent
WORK_DIR = Path(os.environ.get('WORK_DIR', BASE_DIR / 'work'))
WORK_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = {'mp3', 'wav', 'm4a', 'aac', 'flac', 'ogg', 'opus', 'webm', 'mp4'}
MAX_FILE_SIZE = 100 * 1024 * 1024


def allowed(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def ffmpeg_path():
    path = shutil.which('ffmpeg')
    return path or imageio_ffmpeg.get_ffmpeg_exe()


def write_status(job_dir, state, message='', error=''):
    (job_dir / 'status.json').write_text(
        json.dumps({'state': state, 'message': message, 'error': error}, ensure_ascii=False),
        encoding='utf-8'
    )


def process_job(job_id, level):
    job_dir = WORK_DIR / job_id
    log_path = job_dir / 'process.log'
    try:
        meta_path = job_dir / 'upload.meta'
        meta = json.loads(meta_path.read_text(encoding='utf-8'))
        input_path = job_dir / meta['filename']
        output_path = job_dir / 'lecture_cleaned.mp3'

        if not input_path.exists() or input_path.stat().st_size != int(meta['size']):
            write_status(job_dir, 'error', error='업로드된 원본 파일이 없습니다.')
            return

        settings = {
            'light': ('80', '2.0'),
            'medium': ('100', '3.0'),
            'strong': ('130', '4.0'),
        }
        highpass_hz, comp_ratio = settings.get(level, settings['medium'])
        filters = (
            f'highpass=f={highpass_hz}:p=2,'
            f'acompressor=threshold=0.12:ratio={comp_ratio}:attack=20:release=300:makeup=4,'
            'volume=1.5,'
            'alimiter=limit=0.95:level=disabled'
        )

        cmd = [
            ffmpeg_path(), '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
            '-i', str(input_path),
            '-vn', '-af', filters,
            '-ar', '44100', '-ac', '1',
            '-threads', '1',
            '-c:a', 'libmp3lame', '-b:a', '128k',
            str(output_path)
        ]

        write_status(job_dir, 'processing', '음성을 복원하고 있습니다. 녹음 길이에 따라 시간이 걸릴 수 있습니다.')
        with log_path.open('w', encoding='utf-8') as log:
            log.write('worker started\n')
            log.write('running ffmpeg\n')
            log.flush()
            completed = subprocess.run(
                cmd, stdout=log, stderr=log, text=True,
                timeout=60 * 60 * 6, check=False
            )
            log.write(f'ffmpeg returncode: {completed.returncode}\n')
            log.flush()

        if completed.returncode != 0 or not output_path.exists() or output_path.stat().st_size == 0:
            detail = '음성 변환에 실패했습니다.'
            try:
                log_text = log_path.read_text(encoding='utf-8').strip()
                if log_text:
                    detail += f' FFmpeg: {log_text[-800:]}'
            except Exception:
                pass
            write_status(job_dir, 'error', error=detail)
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


def start_processing(job_id, level):
    # Do not detach the worker from Gunicorn. Render can terminate detached
    # children, which leaves the browser stuck in "processing" forever.
    thread = threading.Thread(target=process_job, args=(job_id, level), daemon=True)
    thread.start()


@app.get('/')
def index():
    return render_template('index.html')


@app.post('/api/create-job')
def create_job():
    data = request.get_json(silent=True) or {}
    filename = secure_filename(str(data.get('filename', '')))
    level = str(data.get('level', 'medium'))
    size = int(data.get('size', 0) or 0)

    if not filename or not allowed(filename):
        return jsonify(error='지원하지 않는 파일 형식입니다.'), 400
    if size <= 0:
        return jsonify(error='파일 크기를 확인할 수 없습니다.'), 400
    if size > MAX_FILE_SIZE:
        return jsonify(error='파일이 너무 큽니다. 최대 100MB까지 지원합니다.'), 413

    job_id = uuid.uuid4().hex
    job_dir = WORK_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    (job_dir / 'upload.meta').write_text(
        json.dumps({'filename': filename, 'size': size, 'level': level}, ensure_ascii=False),
        encoding='utf-8'
    )
    (job_dir / filename).touch()
    write_status(job_dir, 'uploading', '파일 업로드 준비 중...')
    return jsonify(ok=True, job_id=job_id)


@app.post('/api/upload-chunk/<job_id>')
def upload_chunk(job_id):
    if '/' in job_id or '\\' in job_id or not job_id.isalnum():
        return jsonify(error='잘못된 요청입니다.'), 400

    job_dir = WORK_DIR / job_id
    meta_path = job_dir / 'upload.meta'
    if not meta_path.exists():
        return jsonify(error='업로드 작업을 찾을 수 없습니다.'), 404

    try:
        meta = json.loads(meta_path.read_text(encoding='utf-8'))
        index = int(request.headers.get('X-Chunk-Index', '-1'))
        total = int(request.headers.get('X-Total-Chunks', '0'))
        if index < 0 or total <= 0 or index >= total:
            return jsonify(error='잘못된 업로드 조각입니다.'), 400

        input_path = job_dir / meta['filename']
        chunk = request.get_data(cache=False)
        if not chunk:
            return jsonify(error='빈 업로드 조각입니다.'), 400

        with input_path.open('ab') as f:
            f.write(chunk)

        received = input_path.stat().st_size
        write_status(job_dir, 'uploading', f'파일 업로드 중... {min(100, round(received / meta["size"] * 100))}%')

        if index == total - 1:
            if received != meta['size']:
                write_status(job_dir, 'error', error='파일 업로드 크기가 일치하지 않습니다.')
                return jsonify(error='파일 업로드가 완전하지 않습니다.'), 400

            level = meta.get('level', 'medium')
            write_status(job_dir, 'queued', '업로드 완료. 음성 복원을 시작합니다.')
            start_processing(job_id, level)
            return jsonify(ok=True, complete=True, status_url=f'/api/status/{job_id}')

        return jsonify(ok=True, complete=False)
    except Exception as exc:
        write_status(job_dir, 'error', error=f'업로드 중 오류가 발생했습니다: {exc}')
        return jsonify(error=f'업로드 중 오류가 발생했습니다: {exc}'), 500


@app.get('/api/status/<job_id>')
def status(job_id):
    if '/' in job_id or '\\' in job_id or not job_id.isalnum():
        return jsonify(error='잘못된 요청입니다.'), 400
    status_path = WORK_DIR / job_id / 'status.json'
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
    return jsonify(error='업로드 조각이 너무 큽니다. 다시 시도해주세요.'), 413


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=False)
