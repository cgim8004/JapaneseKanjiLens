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

function setFile(file) {
  if (!file) return;
  selectedFile = file;
  const max = 2 * 1024 * 1024 * 1024;
  if (file.size > max) {
    showError('파일이 2GB를 초과합니다.');
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

processBtn.addEventListener('click', async () => {
  if (!selectedFile) return;
  processBtn.disabled = true;
  result.classList.add('hidden');
  errorBox.classList.add('hidden');
  progress.classList.remove('hidden');
  statusText.textContent = '대용량 파일은 업로드와 변환에 시간이 걸릴 수 있습니다.';

  const form = new FormData();
  form.append('audio', selectedFile);
  form.append('level', document.querySelector('input[name="level"]:checked').value);

  try {
    const response = await fetch('/api/process', { method: 'POST', body: form });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || '처리에 실패했습니다.');

    progress.classList.add('hidden');
    result.classList.remove('hidden');
    downloadBtn.href = data.download_url;
  } catch (error) {
    showError(error.message || '알 수 없는 오류가 발생했습니다.');
    processBtn.disabled = false;
  }
});
