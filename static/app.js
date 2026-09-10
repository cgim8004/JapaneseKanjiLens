const fileInput = document.getElementById('audioFile');
const dropzone = document.getElementById('dropzone');
const processBtn = document.getElementById('processBtn');
const fileTitle = document.getElementById('fileTitle');
const fileMeta = document.getElementById('fileMeta');
const progress = document.getElementById('progress');
const statusText = document.getElementById('status');
const result = document.getElementById('result');
const errorBox = document.getElementById('error');
const downloadBtn = document.getElementById('downloadBtn');

let selectedFile = null;
let pollTimer = null;

function setFile(file) {
  if (!file) return;
  selectedFile = file;
  const max = 100 * 1024 * 1024;
  if (file.size > max) {
    showError('파일이 100MB를 초과합니다.');
    selectedFile = null;
    processBtn.disabled = true;
    return;
  }
  fileTitle.textContent = file.name;
  fileMeta.textContent = `${(file.size / 1024 / 1024).toFixed(1)} MB · ${file.type || '오디오 파일'}`;
  processBtn.disabled = false;
  result.classList.add('hidden');
  errorBox.classList.add('hidden');
}

fileInput.addEventListener('change', () => setFile(fileInput.files[0]));

['dragenter', 'dragover'].forEach(type => dropzone.addEventListener(type, e => {
  e.preventDefault();
  dropzone.classList.add('dragging');
}));
['dragleave', 'drop'].forEach(type => dropzone.addEventListener(type, e => {
  e.preventDefault();
  dropzone.classList.remove('dragging');
}));
dropzone.addEventListener('drop', e => setFile(e.dataTransfer.files[0]));

function showError(message) {
  errorBox.textContent = message;
  errorBox.classList.remove('hidden');
  progress.classList.add('hidden');
}

function postJson(url, body) {
  return fetch(url, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body),
  }).then(async response => {
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.error || `서버 오류 (${response.status})`);
    return data;
  });
}

function uploadChunk(url, blob, index, total) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', url);
    xhr.setRequestHeader('Content-Type', 'application/octet-stream');
    xhr.setRequestHeader('X-Chunk-Index', String(index));
    xhr.setRequestHeader('X-Total-Chunks', String(total));
    xhr.onload = () => {
      let data = {};
      try { data = JSON.parse(xhr.responseText || '{}'); } catch (_) {}
      if (xhr.status >= 200 && xhr.status < 300) resolve(data);
      else reject(new Error(data.error || `업로드 오류 (${xhr.status})`));
    };
    xhr.onerror = () => reject(new Error('서버와 연결이 끊어졌습니다.'));
    xhr.ontimeout = () => reject(new Error('업로드 시간이 초과되었습니다.'));
    xhr.timeout = 120000;
    xhr.send(blob);
  });
}

async function uploadFileInChunks() {
  const CHUNK_SIZE = 4 * 1024 * 1024;
  const total = Math.ceil(selectedFile.size / CHUNK_SIZE);
  const level = document.querySelector('input[name="level"]:checked').value;

  const created = await postJson('/api/create-job', {
    filename: selectedFile.name,
    size: selectedFile.size,
    level,
  });

  for (let index = 0; index < total; index++) {
    const start = index * CHUNK_SIZE;
    const end = Math.min(selectedFile.size, start + CHUNK_SIZE);
    await uploadChunk(`/api/upload-chunk/${created.job_id}`, selectedFile.slice(start, end), index, total);
    const percent = Math.round((end / selectedFile.size) * 100);
    statusText.textContent = `파일 업로드 중... ${percent}% (${index + 1}/${total})`;
  }

  return {job_id: created.job_id, status_url: `/api/status/${created.job_id}`};
}

function pollStatus(statusUrl) {
  clearTimeout(pollTimer);
  const check = async () => {
    try {
      const response = await fetch(statusUrl, {cache: 'no-store'});
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || '작업 상태를 확인할 수 없습니다.');

      if (data.state === 'done') {
        progress.classList.add('hidden');
        result.classList.remove('hidden');
        downloadBtn.href = data.download_url;
        processBtn.disabled = false;
        return;
      }

      if (data.state === 'error') {
        showError(data.error || '음성 처리에 실패했습니다.');
        processBtn.disabled = false;
        return;
      }

      statusText.textContent = data.message || '음성을 처리하고 있습니다...';
      pollTimer = setTimeout(check, 2000);
    } catch (error) {
      showError(error.message || '작업 상태를 확인할 수 없습니다.');
      processBtn.disabled = false;
    }
  };
  check();
}

processBtn.addEventListener('click', async () => {
  if (!selectedFile) return;
  processBtn.disabled = true;
  result.classList.add('hidden');
  errorBox.classList.add('hidden');
  progress.classList.remove('hidden');
  statusText.textContent = '업로드 준비 중...';

  try {
    const job = await uploadFileInChunks();
    statusText.textContent = '업로드 완료. 음성 복원을 시작합니다...';
    pollStatus(job.status_url);
  } catch (error) {
    showError(error.message || '업로드에 실패했습니다.');
    processBtn.disabled = false;
  }
});
