const $ = (id) => document.getElementById(id);
const state = {
  config: {}, formats: [], formatsCache: new Map(), selectedFormat: '', tempFormat: '', tempVideoFormat: '', tempAudioFormat: '', lastResult: null,
  renderedPreviewKey: '', running: false, conflict: null, tooltipTimer: null, pinnedTooltip: false,
};

const fields = ['url','download_dir','filename_template','proxy_enabled','proxy','cookies_enabled','cookies_file','section_enabled','section_start','section_end','impersonate_enabled','impersonate_target','deno_enabled','audio_format','selected_format','extra_args'];

function showMessage(text, type='ok', options={}) {
  const toast = $('toast');
  $('toastText').textContent = text || '';
  toast.className = `toast ${type}${text ? '' : ' hidden'}`;
  $('toastResultBtn').classList.toggle('hidden', !options.resultAction);
}

function hideMessage() { $('toast').classList.add('hidden'); }

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
    deno_enabled: $('deno_enabled').checked,
    download_mode: getMode(),
    audio_format: $('audio_format').value,
    format_mode: getMode() === 'manual' ? 'manual' : 'auto',
    selected_format: $('selected_format').value.trim(),
    extra_args: $('extra_args').value.trim(),
  };
}

function collectFormatRequest() {
  const c = collectConfig();
  return { url: c.last_url, proxy_enabled: c.proxy_enabled, proxy: c.proxy, cookies_enabled: c.cookies_enabled, cookies_file: c.cookies_file, impersonate_enabled: c.impersonate_enabled, impersonate_target: c.impersonate_target, deno_enabled: c.deno_enabled, extra_args: c.extra_args };
}

function collectDownloadRequest(policy='ask') {
  const c = collectConfig();
  return { ...c, url: c.last_url, conflict_policy: policy };
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
  state.selectedFormat = config.selected_format || '';
  setMode(config.download_mode || 'video');
  updateControls();
}

function validateClient(skipManual=false) {
  const c = collectConfig();
  if (!c.last_url) return 'URL не указан';
  if (c.proxy_enabled && !c.proxy) return 'Proxy включён, но строка proxy пустая';
  if (c.cookies_enabled && !c.cookies_file) return 'Cookies-файл включён, но путь не указан';
  if (c.impersonate_enabled && !c.impersonate_target) return 'Impersonate включён, но target не выбран';
  if (c.section_enabled && (!c.section_start || !c.section_end)) return 'Фрагмент включён, но время не указано';
  if (!skipManual && c.download_mode === 'manual' && !c.selected_format) return 'В ручном режиме формат не выбран';
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
  $('chooseCachedFormatsBtn').disabled = !hasUrl || !findCachedFormats();
  $('stopBtn').disabled = !state.running;
  $('audio_format').disabled = getMode() !== 'audio';
  $('selected_format').disabled = false;
  $('showResultBtn').disabled = !state.lastResult?.file;
  $('previewResultBtn').disabled = !state.lastResult?.file;
}

async function api(path, options={}) {
  const response = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...options });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);
  return data;
}

async function loadConfig() { applyConfig((await api('/api/config')).config); }
async function saveConfig(showToast=true) {
  await api('/api/config', { method:'POST', body: JSON.stringify(collectConfig()) });
  if (showToast) showMessage('Настройки сохранены');
}

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
    const optional = item.optional ? '<span class="warn">опционально</span>' : '';
    return `<div class="env-card"><strong>${escapeHtml(key)}</strong> ${optional}<p class="${ok ? 'ok' : 'warn'}">${ok ? 'OK' : 'Not found / Error'}</p><p>${escapeHtml(item.path || '')}</p><p>${escapeHtml(item.version || item.error || '')}</p></div>`;
  }).join('');
}

function openModal(id) { $(id).classList.remove('hidden'); }
function closeModal(id) {
  $(id).classList.add('hidden');
  if (id === 'resultModal') stopPreviewPlayback();
}

function formatCacheKey() {
  return JSON.stringify(collectFormatRequest());
}

function findCachedFormats() {
  return state.formatsCache.get(formatCacheKey());
}

function showFormatsFromData(data, fromCache=false) {
  state.formats = data.formats || [];
  $('rawFormats').textContent = data.raw_output || '';
  $('commandLine').value = data.command || '';
  $('formatsLoading').classList.add('hidden');
  $('formatsContent').classList.remove('hidden');
  renderFormats();
  if (fromCache) showMessage(`Показан сохранённый список форматов: ${state.formats.length}`);
  else if (!data.success) showMessage(data.error || 'yt-dlp -F завершился с ошибкой', 'error');
  else showMessage(`Получено форматов: ${state.formats.length}`);
}

function prepareFormatsModal() {
  state.tempFormat = $('selected_format').value.trim();
  const parts = state.tempFormat.split('+');
  state.tempVideoFormat = parts[0] || '';
  state.tempAudioFormat = parts.length > 1 ? parts.slice(1).join('+') : '';
  $('formatFieldMirror').value = state.tempFormat;
  $('formatsBody').innerHTML = '';
  $('rawFormats').textContent = '';
  openModal('formatsModal');
}

async function requestFormats() {
  const error = validateClient(true);
  if (error) { showMessage(error, 'error'); return; }
  await saveConfig(false);
  prepareFormatsModal();
  $('formatsLoading').classList.remove('hidden');
  $('formatsContent').classList.add('hidden');
  showMessage('Запрашиваю доступные форматы...');
  const data = await api('/api/formats', { method:'POST', body: JSON.stringify(collectFormatRequest()) });
  state.formatsCache.set(formatCacheKey(), data);
  showFormatsFromData(data, false);
  updateControls();
}

function openCachedFormats() {
  const error = validateClient(true);
  if (error) { showMessage(error, 'error'); return; }
  const cached = findCachedFormats();
  if (!cached) { showMessage('Для этой ссылки ещё нет полученного списка форматов. Нажмите «Запросить форматы».', 'error'); return; }
  prepareFormatsModal();
  showFormatsFromData(cached, true);
}

function formatKind(format) {
  const raw = `${format.raw || ''} ${format.resolution || ''} ${format.video || ''} ${format.audio || ''}`.toLowerCase();
  const audioOnly = raw.includes('audio only') || raw.includes('audio-only') || format.resolution === 'audio';
  const hasVideo = Boolean(format.video) && !audioOnly;
  const hasAudio = Boolean(format.audio) || audioOnly;
  return { hasVideo, hasAudio, audioOnly };
}

function buildManualFormat() {
  const video = state.tempVideoFormat.trim();
  const audio = state.tempAudioFormat.trim();
  if (!video) return audio;
  return audio ? `${video}+${audio}` : video;
}

function renderFormats() {
  $('pickedVideoFormat').textContent = state.tempVideoFormat || '—';
  $('pickedAudioFormat').textContent = state.tempAudioFormat || '—';
  $('formatsBody').innerHTML = state.formats.map((f, idx) => {
    const kind = formatKind(f);
    const selected = [state.tempVideoFormat, state.tempAudioFormat].includes(f.format_id) || f.format_id === state.tempFormat;
    const actions = `<button type="button" data-format-role="video" data-index="${idx}">${kind.audioOnly ? 'Готовый' : 'Видео'}</button> ${kind.hasAudio ? `<button type="button" data-format-role="audio" data-index="${idx}">Аудио</button>` : ''}`;
    return `<tr data-index="${idx}" class="${selected ? 'selected' : ''}"><td>${actions}</td><td>${escapeHtml(f.format_id)}</td><td>${escapeHtml(f.extension)}</td><td>${escapeHtml(f.resolution)}</td><td>${escapeHtml(f.fps)}</td><td>${escapeHtml(f.video)}</td><td>${escapeHtml(f.audio)}</td><td>${escapeHtml(f.size)}</td><td>${escapeHtml(f.note)}</td><td>${escapeHtml(f.raw)}</td></tr>`;
  }).join('');
}

function chooseFormat(formatId, role='video') {
  if (role === 'audio') state.tempAudioFormat = formatId;
  else state.tempVideoFormat = formatId;
  state.tempFormat = buildManualFormat();
  $('formatFieldMirror').value = state.tempFormat;
  renderFormats();
}

function applySelectedFormat(formatId) {
  if (!formatId) { showMessage('Формат не выбран', 'error'); return; }
  state.selectedFormat = formatId;
  $('selected_format').value = formatId;
  setMode('manual');
  closeModal('formatsModal');
  showMessage(`Выбран формат ${formatId}`);
}

async function resolveConflict(conflict) {
  state.conflict = conflict;
  $('conflictPath').textContent = conflict.path || '';
  openModal('conflictModal');
  return new Promise(resolve => {
    state.conflictResolve = resolve;
  });
}

function closeConflict(choice) {
  closeModal('conflictModal');
  const resolve = state.conflictResolve;
  state.conflictResolve = null;
  if (resolve) resolve(choice);
}

async function performDownload(policy='ask') {
  const data = await api('/api/download', { method:'POST', body: JSON.stringify(collectDownloadRequest(policy)) });
  if (data.conflict) {
    const choice = await resolveConflict(data);
    if (choice === 'cancel') { showMessage('Загрузка отменена'); return; }
    if (choice === 'rename') {
      $('filename_template').value = data.suggested_template || $('filename_template').value;
      await performDownload('rename');
      return;
    }
    if (choice === 'overwrite') {
      await performDownload('overwrite');
      return;
    }
    return;
  }
  state.running = true;
  $('statusBadge').textContent = 'Идёт загрузка';
  updateControls();
  showMessage(`Загрузка запущена: ${data.job_id}`);
  switchTab('logs');
}

async function startDownload() {
  const error = validateClient();
  if (error) { showMessage(error, 'error'); return; }
  await saveConfig(false);
  await performDownload('ask');
}

async function stopDownload() {
  const data = await api('/api/download/stop', { method:'POST', body:'{}' });
  showMessage(data.message, data.success ? 'ok' : 'error');
}

function setLogText(text) {
  const output = $('logOutput');
  const nearBottom = output.scrollHeight - output.scrollTop - output.clientHeight < 48;
  output.textContent = text;
  if (nearBottom) output.scrollTop = output.scrollHeight;
}

async function refreshLogs() {
  const data = await api('/api/logs');
  state.running = Boolean(data.running);
  $('commandLine').value = data.command || '';
  setLogText((data.logs || []).join('\n'));
  $('statusBadge').textContent = data.status || 'idle';
  if (data.result && data.result.file) renderResult(data.result);
  updateControls();
}

function resultInfoHtml(result) {
  return `<dt>Файл</dt><dd>${escapeHtml(result.file || '')}</dd><dt>Папка</dt><dd>${escapeHtml(result.folder || '')}</dd><dt>Размер</dt><dd>${formatBytes(result.size || 0)}</dd><dt>Статус</dt><dd>${escapeHtml(result.status || '')}</dd>`;
}

function renderResult(result) {
  state.lastResult = result;
  $('resultInfo').innerHTML = resultInfoHtml(result);
  $('openFileBtn').disabled = !result.file;
  $('openFolderBtn').disabled = !result.folder;
  updateControls();
}

function openResultModal() {
  const result = state.lastResult;
  if (!result) return;
  $('resultModalInfo').innerHTML = resultInfoHtml(result);
  const previewKey = `${result.preview_type || 'none'}|${result.preview_url || ''}`;
  const preview = $('resultModalPreview');
  if (previewKey !== state.renderedPreviewKey) {
    state.renderedPreviewKey = previewKey;
    if (result.preview_type === 'video') preview.innerHTML = `<video controls preload="metadata" src="${escapeAttr(result.preview_url)}"></video>`;
    else if (result.preview_type === 'audio') preview.innerHTML = `<audio controls preload="metadata" src="${escapeAttr(result.preview_url)}"></audio>`;
    else preview.innerHTML = '<p>Предпросмотр в браузере для этого формата может быть недоступен. Используйте кнопку “Открыть файл”.</p>';
  }
  const media = preview.querySelector('video, audio');
  if (media) {
    const savedVolume = Number(localStorage.getItem('previewVolume'));
    if (!Number.isNaN(savedVolume)) media.volume = Math.min(1, Math.max(0, savedVolume));
    media.addEventListener('volumechange', () => localStorage.setItem('previewVolume', String(media.volume)), { passive:true });
  }
  openModal('resultModal');
}

function stopPreviewPlayback() {
  const media = $('resultModalPreview').querySelector('video, audio');
  if (media) media.pause();
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
  if (item.format && !['video','video_only','audio'].includes(item.format)) $('selected_format').value = item.format;
  switchTab('download');
  updateControls();
}

async function openPath(endpoint, path) { await api(endpoint, { method:'POST', body: JSON.stringify({ path }) }); }

function escapeHtml(value) { return String(value ?? '').replace(/[&<>"]/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[ch])); }
function escapeAttr(value) { return escapeHtml(value).replace(/'/g, '&#39;'); }
function formatBytes(bytes) { if (!bytes) return '0 B'; const units=['B','KB','MB','GB']; let n=bytes, i=0; while(n>=1024 && i<units.length-1){n/=1024;i++;} return `${n.toFixed(i ? 1 : 0)} ${units[i]}`; }

function showTooltip(target, pin=false) {
  const text = target.dataset.help;
  if (!text) return;
  const tooltip = $('tooltip');
  tooltip.textContent = text;
  tooltip.classList.remove('hidden');
  state.pinnedTooltip = pin;
  const rect = target.getBoundingClientRect();
  const tipRect = tooltip.getBoundingClientRect();
  let left = rect.left + rect.width / 2 - tipRect.width / 2;
  left = Math.max(8, Math.min(left, window.innerWidth - tipRect.width - 8));
  let top = rect.bottom + 8;
  if (top + tipRect.height > window.innerHeight - 8) top = rect.top - tipRect.height - 8;
  tooltip.style.left = `${left}px`;
  tooltip.style.top = `${Math.max(8, top)}px`;
}

function hideTooltip(force=false) {
  if (state.pinnedTooltip && !force) return;
  clearTimeout(state.tooltipTimer);
  $('tooltip').classList.add('hidden');
  state.pinnedTooltip = false;
}

function setupTooltips() {
  document.querySelectorAll('.help').forEach(help => {
    help.addEventListener('mouseenter', () => { state.tooltipTimer = setTimeout(() => showTooltip(help), 650); });
    help.addEventListener('mouseleave', () => hideTooltip());
    help.addEventListener('focus', () => { state.tooltipTimer = setTimeout(() => showTooltip(help), 650); });
    help.addEventListener('blur', () => hideTooltip());
    help.addEventListener('click', event => { event.stopPropagation(); showTooltip(help, true); });
  });
  document.addEventListener('click', event => { if (!event.target.closest('.help') && !event.target.closest('#tooltip')) hideTooltip(true); });
}

function setupEvents() {
  document.querySelectorAll('.tab').forEach(btn => btn.addEventListener('click', () => switchTab(btn.dataset.tab)));
  fields.forEach(id => { const el = $(id); if (el) el.addEventListener('input', () => { if (id === 'url') { state.selectedFormat = ''; $('selected_format').value = ''; $('formatFieldMirror').value = ''; } updateControls(); }); });
  document.querySelectorAll('input[name="download_mode"]').forEach(el => el.addEventListener('change', updateControls));
  $('toastClose').addEventListener('click', hideMessage);
  $('toastResultBtn').addEventListener('click', openResultModal);
  $('saveConfigBtn').addEventListener('click', () => saveConfig().catch(e => showMessage(e.message, 'error')));
  $('formatsBtn').addEventListener('click', () => requestFormats().catch(e => { closeModal('formatsModal'); showMessage(e.message, 'error'); }));
  $('chooseCachedFormatsBtn').addEventListener('click', openCachedFormats);
  $('downloadBtn').addEventListener('click', () => startDownload().catch(e => showMessage(e.message, 'error')));
  $('stopBtn').addEventListener('click', () => stopDownload().catch(e => showMessage(e.message, 'error')));
  $('formatsBody').addEventListener('click', e => { const button = e.target.closest('[data-format-role]'); if (!button) return; chooseFormat(state.formats[Number(button.dataset.index)].format_id, button.dataset.formatRole); });
  $('formatFieldMirror').addEventListener('input', () => { state.tempFormat = $('formatFieldMirror').value.trim(); const parts = state.tempFormat.split('+'); state.tempVideoFormat = parts[0] || ''; state.tempAudioFormat = parts.length > 1 ? parts.slice(1).join('+') : ''; renderFormats(); });
  $('useFormatBtn').addEventListener('click', () => applySelectedFormat($('formatFieldMirror').value.trim() || state.tempFormat));
  $('closeFormatsModal').addEventListener('click', () => closeModal('formatsModal'));
  $('copyCommandBtn').addEventListener('click', () => navigator.clipboard.writeText($('commandLine').value));
  $('copyLogBtn').addEventListener('click', () => navigator.clipboard.writeText($('logOutput').textContent));
  $('clearLogBtn').addEventListener('click', async () => { await api('/api/logs/clear', {method:'POST', body:'{}'}); await refreshLogs(); });
  $('openFileBtn').addEventListener('click', () => state.lastResult && openPath('/api/open-file', state.lastResult.file));
  $('openFolderBtn').addEventListener('click', () => state.lastResult && openPath('/api/open-folder', state.lastResult.folder || state.lastResult.file));
  $('showResultBtn').addEventListener('click', openResultModal);
  $('previewResultBtn').addEventListener('click', openResultModal);
  $('closeResultModal').addEventListener('click', () => closeModal('resultModal'));
  $('modalOpenFileBtn').addEventListener('click', () => state.lastResult && openPath('/api/open-file', state.lastResult.file));
  $('modalOpenFolderBtn').addEventListener('click', () => state.lastResult && openPath('/api/open-folder', state.lastResult.folder || state.lastResult.file));
  $('conflictRenameBtn').addEventListener('click', () => closeConflict('rename'));
  $('conflictOverwriteBtn').addEventListener('click', () => closeConflict('overwrite'));
  $('conflictCancelBtn').addEventListener('click', () => closeConflict('cancel'));
  document.querySelectorAll('[data-close-modal]').forEach(el => el.addEventListener('click', () => closeModal(el.dataset.closeModal)));
  $('refreshEnvBtn').addEventListener('click', () => refreshEnvironment().catch(e => showMessage(e.message, 'error')));
  document.querySelectorAll('[data-tool]').forEach(btn => btn.addEventListener('click', async () => { const data = await api('/api/tools', {method:'POST', body:JSON.stringify({action:btn.dataset.tool})}); $('toolOutput').textContent = data.output; switchTab('settings'); }));
  $('clearHistoryBtn').addEventListener('click', async () => { await api('/api/history/clear', {method:'POST', body:'{}'}); await loadHistory(); });
  $('historyBody').addEventListener('click', async e => { const items = JSON.parse($('historyBody').dataset.items || '[]'); const repeat = e.target.dataset.repeat; const openFile = e.target.dataset.openFile; const openFolder = e.target.dataset.openFolder; if (repeat !== undefined) repeatHistory(items[Number(repeat)]); if (openFile !== undefined) await openPath('/api/open-file', items[Number(openFile)].output_file); if (openFolder !== undefined) await openPath('/api/open-folder', items[Number(openFolder)].output_file || items[Number(openFolder)].download_dir); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape') { closeModal('formatsModal'); closeModal('resultModal'); if (!$('conflictModal').classList.contains('hidden')) closeConflict('cancel'); hideTooltip(true); } });
  setupTooltips();
}

function appendLogLine(line) {
  const output = $('logOutput');
  const nearBottom = output.scrollHeight - output.scrollTop - output.clientHeight < 48;
  output.textContent += `${output.textContent ? '\n' : ''}${line}`;
  if (nearBottom) output.scrollTop = output.scrollHeight;
}

function setupSse() {
  const source = new EventSource('/api/events');
  source.onmessage = async (event) => {
    const data = JSON.parse(event.data);
    if (data.type === 'log') appendLogLine(`[${data.datetime}] ${data.message}`);
    if (data.type === 'result' && data.result) {
      renderResult(data.result);
      showMessage('Загрузка завершена', 'ok', { resultAction: true });
    }
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
