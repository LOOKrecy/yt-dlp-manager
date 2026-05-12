const configFields = [
  "last_url",
  "download_dir",
  "proxy_enabled",
  "proxy_url",
  "cookies_enabled",
  "cookies_file",
  "section_enabled",
  "section_start",
  "section_end",
  "impersonate_enabled",
  "impersonate_target",
  "download_mode",
  "audio_format",
  "format_mode",
  "selected_format",
  "extra_args",
  "embed_metadata",
  "embed_thumbnail",
  "write_subtitles",
  "write_auto_subtitles",
  "subtitles_language",
  "playlist_enabled",
  "playlist_start",
  "playlist_end",
  "overwrite_files",
  "restrict_filenames",
  "output_template",
];

const statusList = document.querySelector("#status");
const backendStatus = statusList?.querySelector("dd");
const runningStatus = document.querySelector("#running-status");
const toast = document.querySelector("#toast");
const urlInput = document.querySelector("#url");
const requiresUrlButtons = document.querySelectorAll(".requires-url");
const formatsTableBody = document.querySelector("#formats-table tbody");
const formatsMessage = document.querySelector("#formats-message");
const formatsRaw = document.querySelector("#formats-raw");
const logsOutput = document.querySelector("#logs-output");
const logPath = document.querySelector("#log-path");
const resultCard = document.querySelector("#result-card");
const historyTableBody = document.querySelector("#history-table tbody");
const environmentDirectories = document.querySelector("#environment-directories");
const environmentTools = document.querySelector("#environment-tools");

let saveTimer = null;
let logTimer = null;
let selectedFormatCode = "";

const statusLabels = {
  true: "Готово",
  false: "Не найдено",
};

function showToast(message, variant = "success") {
  if (!toast) {
    return;
  }

  toast.textContent = message;
  toast.className = `toast ${variant}`;
  toast.hidden = false;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    toast.hidden = true;
  }, 3500);
}

function setButtonLoading(button, isLoading, loadingText) {
  if (!button) {
    return;
  }

  if (isLoading) {
    button.dataset.defaultText = button.textContent;
    button.textContent = loadingText;
    button.disabled = true;
    return;
  }

  button.textContent = button.dataset.defaultText || button.textContent;
  updateUrlButtons();
}

function updateUrlButtons() {
  const hasUrl = Boolean(urlInput?.value.trim());
  requiresUrlButtons.forEach((button) => {
    button.disabled = !hasUrl;
  });
}

function apiErrorMessage(error) {
  if (typeof error === "string") {
    return error;
  }
  return error?.message || "Неизвестная ошибка";
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });

  const contentType = response.headers.get("content-type") || "";
  const data = contentType.includes("application/json") ? await response.json() : await response.text();

  if (!response.ok) {
    const detail = typeof data === "object" && data !== null ? data.detail : data;
    throw new Error(detail || `HTTP ${response.status}`);
  }

  return data;
}

function fieldByName(name) {
  return document.querySelector(`[name="${name}"]`);
}

function readFieldValue(field) {
  if (!field) {
    return "";
  }
  if (field.type === "checkbox") {
    return field.checked;
  }
  return field.value;
}

function writeFieldValue(field, value) {
  if (!field || value === undefined || value === null) {
    return;
  }
  if (field.type === "checkbox") {
    field.checked = Boolean(value);
    return;
  }
  field.value = value;
}

function collectConfig() {
  const config = {};
  configFields.forEach((name) => {
    config[name] = readFieldValue(fieldByName(name));
  });
  return config;
}

function buildRequestPayload() {
  const config = collectConfig();
  return {
    ...config,
    url: config.last_url.trim(),
    selected_format: selectedFormatCode || config.selected_format.trim(),
  };
}

function applyConfig(config) {
  configFields.forEach((name) => writeFieldValue(fieldByName(name), config[name]));
  selectedFormatCode = config.selected_format || "";
  updateUrlButtons();
  updateDependentControls();
}

function queueSaveConfig() {
  window.clearTimeout(saveTimer);
  saveTimer = window.setTimeout(() => {
    saveConfig(false).catch((error) => console.error("Config autosave failed", error));
  }, 450);
}

async function loadConfig() {
  try {
    const config = await requestJson("/api/config");
    applyConfig(config);
  } catch (error) {
    showToast(`Не удалось загрузить конфигурацию: ${apiErrorMessage(error)}`, "error");
  }
}

async function saveConfig(showSuccess = true) {
  const config = collectConfig();
  const saved = await requestJson("/api/config", {
    method: "POST",
    body: JSON.stringify(config),
  });
  applyConfig(saved);
  if (showSuccess) {
    showToast("Конфигурация сохранена");
  }
  return saved;
}

function updateDependentControls() {
  document.querySelectorAll("[data-toggle-controls]").forEach((checkbox) => {
    const container = document.querySelector(`#${checkbox.dataset.toggleControls}`);
    if (!container) {
      return;
    }

    container.classList.toggle("is-disabled", !checkbox.checked);
    container.querySelectorAll("input, select, button").forEach((control) => {
      control.disabled = !checkbox.checked;
    });
  });
}

function switchTab(targetName) {
  document.querySelectorAll(".tab-button").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.tabTarget === targetName);
  });
  document.querySelectorAll(".panel").forEach((panel) => {
    const isTarget = panel.id === `tab-${targetName}`;
    panel.classList.toggle("is-active", isTarget);
    panel.hidden = !isTarget;
  });
}

function renderEnvironmentList(container, items) {
  if (!container) {
    return;
  }

  container.replaceChildren();
  Object.values(items).forEach((item) => {
    const row = document.createElement("div");
    const term = document.createElement("dt");
    const description = document.createElement("dd");
    const status = document.createElement("span");
    const path = document.createElement("small");

    term.textContent = item.name;
    status.textContent = statusLabels[item.exists];
    status.className = item.exists ? "success" : "error";
    path.textContent = item.path;

    description.append(status, path);
    row.append(term, description);
    container.append(row);
  });
}

function renderEnvironmentError() {
  [environmentDirectories, environmentTools].forEach((container) => {
    if (!container) {
      return;
    }

    const row = document.createElement("div");
    const term = document.createElement("dt");
    const description = document.createElement("dd");
    term.textContent = "Проверка";
    description.textContent = "Недоступна";
    description.classList.add("error");
    row.append(term, description);
    container.replaceChildren(row);
  });
}

async function loadStatus() {
  if (!backendStatus) {
    return;
  }

  try {
    const data = await requestJson("/api/health");
    backendStatus.textContent = data.status === "ok" ? "Работает" : "Неизвестно";
    backendStatus.classList.remove("error");
  } catch (error) {
    backendStatus.textContent = "Недоступен";
    backendStatus.classList.add("error");
    console.error("Health check failed", error);
  }
}

async function loadEnvironment() {
  try {
    const data = await requestJson("/api/environment");
    renderEnvironmentList(environmentDirectories, data.directories);
    renderEnvironmentList(environmentTools, data.tools);
  } catch (error) {
    renderEnvironmentError();
    console.error("Environment check failed", error);
  }
}

function parseFormatOutput(output) {
  return output
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("[") && !line.startsWith("ID ") && !line.startsWith("---"))
    .map((line) => {
      const columns = line.split(/\s+/);
      return {
        code: columns[0] || "",
        extension: columns[1] || "",
        resolution: columns[2] || "",
        note: columns.slice(3).join(" "),
        raw: line,
      };
    })
    .filter((format) => format.code && format.extension);
}

function renderFormats(formats, rawOutput) {
  if (!formatsTableBody) {
    return;
  }

  formatsTableBody.replaceChildren();
  formatsRaw.textContent = rawOutput || "";

  if (!formats.length) {
    formatsMessage.textContent = "Форматы не распознаны. Проверьте raw output.";
    return;
  }

  formatsMessage.textContent = `Найдено форматов: ${formats.length}. Нажмите строку, чтобы выбрать format code.`;
  formats.forEach((format) => {
    const row = document.createElement("tr");
    row.className = "is-clickable";
    row.dataset.formatCode = format.code;
    row.title = format.raw;
    if (format.code === selectedFormatCode) {
      row.classList.add("is-selected");
    }

    [format.code, format.extension, format.resolution, format.note].forEach((value) => {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    });

    row.addEventListener("click", () => selectFormat(format.code));
    formatsTableBody.append(row);
  });
}

function selectFormat(formatCode) {
  selectedFormatCode = formatCode;
  const selectedFormatInput = fieldByName("selected_format");
  const formatMode = fieldByName("format_mode");
  if (selectedFormatInput) {
    selectedFormatInput.value = formatCode;
  }
  if (formatMode) {
    formatMode.value = "selected";
  }

  formatsTableBody?.querySelectorAll("tr").forEach((row) => {
    row.classList.toggle("is-selected", row.dataset.formatCode === formatCode);
  });
  queueSaveConfig();
  showToast(`Выбран format code: ${formatCode}`);
}

async function loadFormats() {
  const button = document.querySelector("#load-formats-button");
  const refreshButton = document.querySelector("#refresh-formats-button");
  const payload = buildRequestPayload();
  if (!payload.url) {
    updateUrlButtons();
    return;
  }

  setButtonLoading(button, true, "Загрузка…");
  setButtonLoading(refreshButton, true, "Загрузка…");
  formatsMessage.textContent = "Запрашиваем форматы…";
  try {
    await saveConfig(false);
    const data = await requestJson("/api/formats", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    renderFormats(parseFormatOutput(data.output), data.output);
    switchTab("formats");
  } catch (error) {
    formatsMessage.textContent = `Ошибка: ${apiErrorMessage(error)}`;
    showToast(`Не удалось получить форматы: ${apiErrorMessage(error)}`, "error");
  } finally {
    setButtonLoading(button, false);
    setButtonLoading(refreshButton, false);
  }
}

function renderResult(data) {
  if (!resultCard) {
    return;
  }

  resultCard.classList.remove("muted");
  resultCard.replaceChildren();
  const list = document.createElement("dl");
  [
    ["Status", data.status],
    ["URL", data.url],
    ["PID", data.pid],
    ["Log", data.log_path],
  ].forEach(([label, value]) => {
    const row = document.createElement("div");
    const term = document.createElement("dt");
    const description = document.createElement("dd");
    term.textContent = label;
    description.textContent = value || "—";
    row.append(term, description);
    list.append(row);
  });
  resultCard.append(list);
}

async function startDownload() {
  const button = document.querySelector("#start-download-button");
  const payload = buildRequestPayload();
  if (!payload.url) {
    updateUrlButtons();
    return;
  }

  setButtonLoading(button, true, "Запуск…");
  try {
    await saveConfig(false);
    const data = await requestJson("/api/download", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    renderResult(data);
    showToast("Загрузка запущена");
    switchTab("logs");
    startLogPolling();
    await loadHistory();
  } catch (error) {
    showToast(`Не удалось запустить загрузку: ${apiErrorMessage(error)}`, "error");
  } finally {
    setButtonLoading(button, false);
  }
}

async function stopDownload() {
  try {
    const data = await requestJson("/api/download/stop", { method: "POST", body: "{}" });
    showToast(data.status === "stopped" ? "Загрузка остановлена" : "Активной загрузки нет");
    await loadLogs();
  } catch (error) {
    showToast(`Не удалось остановить загрузку: ${apiErrorMessage(error)}`, "error");
  }
}

async function loadLogs() {
  try {
    const data = await requestJson("/api/logs?lines=500");
    runningStatus.textContent = data.running ? "Да" : "Нет";
    runningStatus.className = data.running ? "warning" : "success";
    logPath.textContent = data.log_path ? `Log: ${data.log_path}` : "Лог пока не выбран.";
    logsOutput.textContent = data.lines?.length ? data.lines.join("\n") : "Логи пока пусты.";
    logsOutput.scrollTop = logsOutput.scrollHeight;
    if (!data.running) {
      stopLogPolling();
    }
    return data;
  } catch (error) {
    logsOutput.textContent = `Ошибка загрузки логов: ${apiErrorMessage(error)}`;
    stopLogPolling();
    throw error;
  }
}

function startLogPolling() {
  stopLogPolling();
  loadLogs().catch((error) => console.error("Log polling failed", error));
  logTimer = window.setInterval(() => {
    loadLogs().catch((error) => console.error("Log polling failed", error));
  }, 1500);
}

function stopLogPolling() {
  if (logTimer) {
    window.clearInterval(logTimer);
    logTimer = null;
  }
}

function renderHistory(items) {
  if (!historyTableBody) {
    return;
  }

  historyTableBody.replaceChildren();
  if (!items.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 10;
    cell.className = "muted";
    cell.textContent = "История пуста.";
    row.append(cell);
    historyTableBody.append(row);
    return;
  }

  items.forEach((item) => {
    const row = document.createElement("tr");
    const date = item.datetime ? new Date(item.datetime).toLocaleString() : "—";
    [
      date,
      item.title || "—",
      item.url,
      item.download_dir || "—",
      item.output_file || "—",
      item.mode || "—",
      item.format || "—",
      item.status,
      item.error || "—",
    ].forEach((value) => {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.append(cell);
    });

    const actionsCell = document.createElement("td");
    const repeatButton = document.createElement("button");
    repeatButton.className = "button button--secondary button--small";
    repeatButton.type = "button";
    repeatButton.textContent = "Повторить";
    repeatButton.addEventListener("click", () => repeatHistoryItem(item));
    actionsCell.append(repeatButton);
    row.append(actionsCell);

    historyTableBody.append(row);
  });
}

function repeatHistoryItem(item) {
  writeFieldValue(fieldByName("last_url"), item.url || "");
  writeFieldValue(fieldByName("download_dir"), item.download_dir || "Downloads");
  writeFieldValue(fieldByName("output_template"), item.output_file || "%(title)s.%(ext)s");

  if (item.mode) {
    writeFieldValue(fieldByName("download_mode"), item.mode);
  }

  const formatValue = item.format || "";
  selectedFormatCode = "";
  if (["best", "worst"].includes(formatValue)) {
    writeFieldValue(fieldByName("format_mode"), formatValue);
    writeFieldValue(fieldByName("selected_format"), "");
  } else if (item.mode === "audio" && formatValue) {
    writeFieldValue(fieldByName("audio_format"), formatValue);
  } else if (formatValue) {
    writeFieldValue(fieldByName("format_mode"), "selected");
    writeFieldValue(fieldByName("selected_format"), formatValue);
    selectedFormatCode = formatValue;
  }

  updateUrlButtons();
  updateDependentControls();
  queueSaveConfig();
  switchTab("download");
  showToast("Параметры из истории подставлены в форму");
}

async function loadHistory() {
  try {
    const data = await requestJson("/api/history");
    renderHistory(data.items || []);
  } catch (error) {
    showToast(`Не удалось загрузить историю: ${apiErrorMessage(error)}`, "error");
  }
}

async function clearHistory() {
  try {
    const data = await requestJson("/api/history/clear", { method: "POST", body: "{}" });
    renderHistory([]);
    showToast(`История очищена: ${data.deleted}`);
  } catch (error) {
    showToast(`Не удалось очистить историю: ${apiErrorMessage(error)}`, "error");
  }
}

function bindEvents() {
  document.querySelectorAll(".tab-button").forEach((button) => {
    button.addEventListener("click", () => switchTab(button.dataset.tabTarget));
  });

  document.querySelectorAll("input, select").forEach((field) => {
    field.addEventListener("input", () => {
      if (field === urlInput) {
        updateUrlButtons();
      }
      queueSaveConfig();
    });
    field.addEventListener("change", () => {
      updateDependentControls();
      queueSaveConfig();
    });
  });

  document.querySelector("#save-config-button")?.addEventListener("click", () => {
    saveConfig(true).catch((error) => showToast(`Не удалось сохранить: ${apiErrorMessage(error)}`, "error"));
  });
  document.querySelector("#load-formats-button")?.addEventListener("click", loadFormats);
  document.querySelector("#refresh-formats-button")?.addEventListener("click", loadFormats);
  document.querySelector("#start-download-button")?.addEventListener("click", startDownload);
  document.querySelector("#stop-download-button")?.addEventListener("click", stopDownload);
  document.querySelector("#refresh-logs-button")?.addEventListener("click", () => loadLogs().catch(() => undefined));
  document.querySelector("#refresh-history-button")?.addEventListener("click", loadHistory);
  document.querySelector("#clear-history-button")?.addEventListener("click", clearHistory);
}

async function init() {
  bindEvents();
  updateUrlButtons();
  updateDependentControls();
  await Promise.allSettled([loadStatus(), loadEnvironment(), loadConfig(), loadHistory(), loadLogs()]);
}

init();
