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

function pollStatus(statusUrl) {
  clearTimeout(pollTimer);
  const check = async () => {
    try {
      const response = await fetch(statusUrl, { cache: 'no-store' });
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

processBtn.addEventListener('click', () => {
  if (!selectedFile) return;
  processBtn.disabled = true;
  result.classList.add('hidden');
  errorBox.classList.add('hidden');
  progress.classList.remove('hidden');
  statusText.textContent = '파일 업로드 중... 0%';

  const form = new FormData();
  form.append('audio', selectedFile);
  form.append('level', document.querySelector('input[name="level"]:checked').value);

  const xhr = new XMLHttpRequest();
  xhr.open('POST', '/api/process');
  xhr.responseType = 'json';
  xhr.upload.onprogress = event => {
    if (event.lengthComputable) {
      const percent = Math.round((event.loaded / event.total) * 100);
      statusText.textContent = `파일 업로드 중... ${percent}%`;
    }
  };
  xhr.onload = () => {
    const data = xhr.response || {};
    if (xhr.status >= 200 && xhr.status < 300 && data.job_id) {
      statusText.textContent = '업로드 완료. 음성 복원을 시작합니다...';
      pollStatus(data.status_url);
      return;
    }
    showError(data.error || `서버 오류 (${xhr.status})`);
    processBtn.disabled = false;
  };
  xhr.onerror = () => {
    showError('서버와 연결이 끊어졌습니다. 잠시 후 다시 시도해주세요.');
    processBtn.disabled = false;
  };
  xhr.ontimeout = () => {
    showError('업로드 시간이 초과되었습니다.');
    processBtn.disabled = false;
  };
  xhr.send(form);
});
