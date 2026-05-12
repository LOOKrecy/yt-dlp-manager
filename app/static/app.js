const $ = (id) => document.getElementById(id);
const state = { config: {}, formats: [], selectedFormat: '', lastResult: null, running: false };

const fields = ['url','download_dir','filename_template','proxy_enabled','proxy','cookies_enabled','cookies_file','section_enabled','section_start','section_end','impersonate_enabled','impersonate_target','audio_format','selected_format','extra_args'];

function showMessage(text, type='ok') {
  const el = $('message');
  el.textContent = text;
  el.className = `message ${type}`;
  if (!text) el.classList.add('hidden');
}

function switchTab(name) {
  document.querySelectorAll('.tab').forEach(btn => btn.classList.toggle('active', btn.dataset.tab === name));
  document.querySelectorAll('.panel').forEach(panel => panel.classList.toggle('active', panel.id === name));
}

function getMode() { return document.querySelector('input[name="download_mode"]:checked')?.value || 'video'; }
function setMode(value) { document.querySelector(`input[name="download_mode"][value="${value}"]`).checked = true; updateControls(); }

function collectConfig() {
  return {
    last_url: $('url').value.trim(),
    download_dir: $('download_dir').value.trim() || 'Downloads',
    filename_template: $('filename_template').value.trim(),
    proxy_enabled: $('proxy_enabled').checked,
    proxy: $('proxy').value.trim(),
    cookies_enabled: $('cookies_enabled').checked,
    cookies_file: $('cookies_file').value.trim(),
    section_enabled: $('section_enabled').checked,
    section_start: $('section_start').value.trim() || '00:00:00',
    section_end: $('section_end').value.trim() || '00:00:00',
    impersonate_enabled: $('impersonate_enabled').checked,
    impersonate_target: $('impersonate_target').value,
    download_mode: getMode(),
    audio_format: $('audio_format').value,
    format_mode: getMode() === 'manual' ? 'manual' : 'auto',
    selected_format: $('selected_format').value.trim(),
    extra_args: $('extra_args').value.trim(),
  };
}

function collectFormatRequest() {
  const c = collectConfig();
  return { url: c.last_url, proxy_enabled: c.proxy_enabled, proxy: c.proxy, cookies_enabled: c.cookies_enabled, cookies_file: c.cookies_file, impersonate_enabled: c.impersonate_enabled, impersonate_target: c.impersonate_target, extra_args: c.extra_args };
}

function collectDownloadRequest() {
  const c = collectConfig();
  return { ...c, url: c.last_url };
}

function applyConfig(config) {
  state.config = config;
  $('url').value = config.last_url || '';
  for (const id of fields) {
    if (id === 'url') continue;
    const el = $(id);
    if (!el) continue;
    if (el.type === 'checkbox') el.checked = Boolean(config[id]);
    else el.value = config[id] ?? '';
  }
  setMode(config.download_mode || 'video');
  updateControls();
}

function validateClient() {
  const c = collectConfig();
  if (!c.last_url) return 'URL не указан';
  if (c.proxy_enabled && !c.proxy) return 'Proxy включён, но строка proxy пустая';
  if (c.cookies_enabled && !c.cookies_file) return 'Cookies-файл включён, но путь не указан';
  if (c.impersonate_enabled && !c.impersonate_target) return 'Impersonate включён, но target не выбран';
  if (c.section_enabled && (!c.section_start || !c.section_end)) return 'Фрагмент включён, но время не указано';
  if (c.download_mode === 'manual' && !c.selected_format) return 'В ручном режиме формат не выбран';
  return '';
}

function updateControls() {
  const hasUrl = $('url').value.trim().length > 0;
  $('proxy').disabled = !$('proxy_enabled').checked;
  $('cookies_file').disabled = !$('cookies_enabled').checked;
  $('impersonate_target').disabled = !$('impersonate_enabled').checked;
  $('section_start').disabled = !$('section_enabled').checked;
  $('section_end').disabled = !$('section_enabled').checked;
  $('formatsBtn').disabled = !hasUrl || state.running;
  $('downloadBtn').disabled = !hasUrl || state.running || (getMode() === 'manual' && !$('selected_format').value.trim());
  $('stopBtn').disabled = !state.running;
  $('audio_format').disabled = getMode() !== 'audio';
  $('selected_format').disabled = false;
}

async function api(path, options={}) {
  const response = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...options });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
  return data;
}

async function loadConfig() { applyConfig((await api('/api/config')).config); }
async function saveConfig() { await api('/api/config', { method:'POST', body: JSON.stringify(collectConfig()) }); showMessage('Настройки сохранены'); }

async function loadImpersonateTargets() {
  const data = await api('/api/impersonate-targets');
  const select = $('impersonate_target');
  const current = select.value;
  select.innerHTML = '<option value="">Выберите target</option>' + data.targets.map(t => `<option>${escapeHtml(t)}</option>`).join('');
  select.value = current;
}

async function refreshEnvironment() {
  const env = await api('/api/environment?include_versions=true');
  const container = $('environment');
  container.innerHTML = Object.entries(env).map(([key, item]) => {
    const ok = item.exists && (item.writable ?? true);
    return `<div class="env-card"><strong>${escapeHtml(key)}</strong><p class="${ok ? 'ok' : 'warn'}">${ok ? 'OK' : 'Not found / Error'}</p><p>${escapeHtml(item.path || '')}</p><p>${escapeHtml(item.version || item.error || '')}</p></div>`;
  }).join('');
}

async function requestFormats() {
  const error = validateClient();
  if (error && error !== 'В ручном режиме формат не выбран') { showMessage(error, 'error'); return; }
  await saveConfig();
  showMessage('Запрашиваем форматы...');
  const data = await api('/api/formats', { method:'POST', body: JSON.stringify(collectFormatRequest()) });
  state.formats = data.formats;
  $('rawFormats').textContent = data.raw_output || '';
  renderFormats();
  $('commandLine').value = data.command || '';
  if (!data.success) showMessage(data.error || 'yt-dlp -F завершился с ошибкой', 'error'); else showMessage(`Получено форматов: ${data.formats.length}`);
  switchTab('formats');
}

function renderFormats() {
  $('formatsBody').innerHTML = state.formats.map((f, idx) => `<tr data-index="${idx}" class="${f.format_id === state.selectedFormat ? 'selected' : ''}"><td>${escapeHtml(f.format_id)}</td><td>${escapeHtml(f.extension)}</td><td>${escapeHtml(f.resolution)}</td><td>${escapeHtml(f.fps)}</td><td>${escapeHtml(f.video)}</td><td>${escapeHtml(f.audio)}</td><td>${escapeHtml(f.size)}</td><td>${escapeHtml(f.note)}</td><td>${escapeHtml(f.raw)}</td></tr>`).join('');
}

function selectFormat(formatId) {
  state.selectedFormat = formatId;
  $('selected_format').value = formatId;
  $('formatFieldMirror').value = formatId;
  setMode('manual');
  renderFormats();
  showMessage(`Выбран формат ${formatId}`);
}

async function startDownload() {
  const error = validateClient();
  if (error) { showMessage(error, 'error'); return; }
  await saveConfig();
  const data = await api('/api/download', { method:'POST', body: JSON.stringify(collectDownloadRequest()) });
  state.running = true;
  $('statusBadge').textContent = 'Идёт загрузка';
  updateControls();
  showMessage(`Загрузка запущена: ${data.job_id}`);
  switchTab('logs');
}

async function stopDownload() {
  const data = await api('/api/download/stop', { method:'POST', body:'{}' });
  showMessage(data.message, data.success ? 'ok' : 'error');
}

async function refreshLogs() {
  const data = await api('/api/logs');
  state.running = Boolean(data.running);
  $('commandLine').value = data.command || '';
  $('logOutput').textContent = (data.logs || []).join('\n');
  $('statusBadge').textContent = data.status || 'idle';
  if (data.result && data.result.file) renderResult(data.result);
  updateControls();
}

function renderResult(result) {
  state.lastResult = result;
  $('resultInfo').innerHTML = `<dt>Файл</dt><dd>${escapeHtml(result.file || '')}</dd><dt>Папка</dt><dd>${escapeHtml(result.folder || '')}</dd><dt>Размер</dt><dd>${formatBytes(result.size || 0)}</dd><dt>Статус</dt><dd>${escapeHtml(result.status || '')}</dd>`;
  $('openFileBtn').disabled = !result.file;
  $('openFolderBtn').disabled = !result.folder;
  const preview = $('preview');
  if (result.preview_type === 'video') preview.innerHTML = `<video controls src="${escapeAttr(result.preview_url)}"></video>`;
  else if (result.preview_type === 'audio') preview.innerHTML = `<audio controls src="${escapeAttr(result.preview_url)}"></audio>`;
  else preview.innerHTML = '<p>Предпросмотр в браузере для этого формата может быть недоступен. Используйте кнопку “Открыть файл”.</p>';
}

async function loadHistory() {
  const data = await api('/api/history');
  $('historyBody').innerHTML = data.history.map((h, idx) => `<tr><td>${escapeHtml(h.datetime)}</td><td>${escapeHtml(h.url)}</td><td>${escapeHtml(h.output_file)}</td><td>${escapeHtml(h.mode)}</td><td>${escapeHtml(h.format)}</td><td>${escapeHtml(h.status)}</td><td><button data-repeat="${idx}">Повторить</button> <button data-open-file="${idx}">Файл</button> <button data-open-folder="${idx}">Папка</button></td></tr>`).join('');
  $('historyBody').dataset.items = JSON.stringify(data.history);
}

function repeatHistory(item) {
  $('url').value = item.url || '';
  $('download_dir').value = item.download_dir || 'Downloads';
  setMode(item.mode || 'video');
  if (item.format && !['video','audio'].includes(item.format)) $('selected_format').value = item.format;
  switchTab('download');
  updateControls();
}

async function openPath(endpoint, path) { await api(endpoint, { method:'POST', body: JSON.stringify({ path }) }); }

function escapeHtml(value) { return String(value ?? '').replace(/[&<>"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[ch])); }
function escapeAttr(value) { return escapeHtml(value).replace(/'/g, '&#39;'); }
function formatBytes(bytes) { if (!bytes) return '0 B'; const units=['B','KB','MB','GB']; let n=bytes, i=0; while(n>=1024 && i<units.length-1){n/=1024;i++;} return `${n.toFixed(i ? 1 : 0)} ${units[i]}`; }

function setupEvents() {
  document.querySelectorAll('.tab').forEach(btn => btn.addEventListener('click', () => switchTab(btn.dataset.tab)));
  fields.forEach(id => { const el = $(id); if (el) el.addEventListener('input', () => { if (id === 'url') { state.selectedFormat = ''; $('selected_format').value = ''; $('formatFieldMirror').value = ''; } updateControls(); }); });
  document.querySelectorAll('input[name="download_mode"]').forEach(el => el.addEventListener('change', updateControls));
  $('saveConfigBtn').addEventListener('click', () => saveConfig().catch(e => showMessage(e.message, 'error')));
  $('formatsBtn').addEventListener('click', () => requestFormats().catch(e => showMessage(e.message, 'error')));
  $('downloadBtn').addEventListener('click', () => startDownload().catch(e => showMessage(e.message, 'error')));
  $('stopBtn').addEventListener('click', () => stopDownload().catch(e => showMessage(e.message, 'error')));
  $('formatsBody').addEventListener('click', e => { const tr = e.target.closest('tr'); if (tr) selectFormat(state.formats[Number(tr.dataset.index)].format_id); });
  $('formatFieldMirror').addEventListener('input', () => { $('selected_format').value = $('formatFieldMirror').value; state.selectedFormat = $('formatFieldMirror').value; updateControls(); });
  $('useFormatBtn').addEventListener('click', () => selectFormat($('formatFieldMirror').value.trim() || state.selectedFormat));
  $('copyCommandBtn').addEventListener('click', () => navigator.clipboard.writeText($('commandLine').value));
  $('copyLogBtn').addEventListener('click', () => navigator.clipboard.writeText($('logOutput').textContent));
  $('clearLogBtn').addEventListener('click', async () => { await api('/api/logs/clear', {method:'POST', body:'{}'}); await refreshLogs(); });
  $('openFileBtn').addEventListener('click', () => state.lastResult && openPath('/api/open-file', state.lastResult.file));
  $('openFolderBtn').addEventListener('click', () => state.lastResult && openPath('/api/open-folder', state.lastResult.folder || state.lastResult.file));
  $('refreshEnvBtn').addEventListener('click', () => refreshEnvironment().catch(e => showMessage(e.message, 'error')));
  document.querySelectorAll('[data-tool]').forEach(btn => btn.addEventListener('click', async () => { const data = await api('/api/tools', {method:'POST', body:JSON.stringify({action:btn.dataset.tool})}); $('toolOutput').textContent = data.output; switchTab('logs'); }));
  $('clearHistoryBtn').addEventListener('click', async () => { await api('/api/history/clear', {method:'POST', body:'{}'}); await loadHistory(); });
  $('historyBody').addEventListener('click', async e => { const items = JSON.parse($('historyBody').dataset.items || '[]'); const repeat = e.target.dataset.repeat; const openFile = e.target.dataset.openFile; const openFolder = e.target.dataset.openFolder; if (repeat !== undefined) repeatHistory(items[Number(repeat)]); if (openFile !== undefined) await openPath('/api/open-file', items[Number(openFile)].output_file); if (openFolder !== undefined) await openPath('/api/open-folder', items[Number(openFolder)].output_file || items[Number(openFolder)].download_dir); });
}

function setupSse() {
  const source = new EventSource('/api/events');
  source.onmessage = async (event) => {
    const data = JSON.parse(event.data);
    if (data.type === 'log') $('logOutput').textContent += `${$('logOutput').textContent ? '\n' : ''}[${data.datetime}] ${data.message}`;
    if (data.type === 'result' && data.result) renderResult(data.result);
    if (data.type === 'status') { await refreshLogs(); await loadHistory(); }
  };
  source.onerror = () => setTimeout(refreshLogs, 1500);
}

async function init() {
  setupEvents();
  await loadConfig();
  await loadImpersonateTargets();
  await refreshEnvironment();
  await refreshLogs();
  await loadHistory();
  setupSse();
  setInterval(refreshLogs, 4000);
}

init().catch(error => showMessage(error.message, 'error'));
