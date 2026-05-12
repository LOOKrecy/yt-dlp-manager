const statusList = document.querySelector("#status");
const backendStatus = statusList?.querySelector("dd");

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

loadStatus();
