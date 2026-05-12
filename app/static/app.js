const statusList = document.querySelector("#status");
const backendStatus = statusList?.querySelector("dd");
const environmentDirectories = document.querySelector("#environment-directories");
const environmentTools = document.querySelector("#environment-tools");

const statusLabels = {
  true: "Готово",
  false: "Не найдено",
};

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
    const response = await fetch("/api/health");
    if (!response.ok) {
      throw new Error(`Unexpected status ${response.status}`);
    }

    const data = await response.json();
    backendStatus.textContent = data.status === "ok" ? "Работает" : "Неизвестно";
  } catch (error) {
    backendStatus.textContent = "Недоступен";
    backendStatus.classList.add("error");
    console.error("Health check failed", error);
  }
}

async function loadEnvironment() {
  try {
    const response = await fetch("/api/environment");
    if (!response.ok) {
      throw new Error(`Unexpected status ${response.status}`);
    }

    const data = await response.json();
    renderEnvironmentList(environmentDirectories, data.directories);
    renderEnvironmentList(environmentTools, data.tools);
  } catch (error) {
    renderEnvironmentError();
    console.error("Environment check failed", error);
  }
}

loadStatus();
loadEnvironment();
