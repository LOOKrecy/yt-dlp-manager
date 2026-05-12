"""FastAPI entry point for the local yt-dlp manager application."""

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config_manager import get_config
from app.history_manager import HistoryManager
from app.models import DownloadRequest, HealthResponse
from app.path_utils import STATIC_DIR, ensure_project_directories, get_environment_status
from app.process_manager import ProcessManager
from app.ytdlp_service import YtDlpService

config = get_config()
process_manager = ProcessManager()
history_manager = HistoryManager()
ytdlp_service = YtDlpService(process_manager)

app = FastAPI(title="yt-dlp Manager", version="0.1.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.on_event("startup")
def on_startup() -> None:
    """Ensure local runtime directories exist before serving requests."""

    ensure_project_directories()


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Return a minimal health-check payload."""

    return HealthResponse()


@app.get("/api/config")
def read_config() -> dict[str, str | int]:
    """Return public local application configuration."""

    return {
        "host": config.host,
        "port": config.port,
        "downloads_dir": str(config.downloads_dir),
        "data_dir": str(config.data_dir),
        "logs_dir": str(config.logs_dir),
    }


@app.get("/api/environment")
def read_environment() -> dict[str, dict[str, dict[str, str | bool]]]:
    """Return local runtime directory and bundled tool availability."""

    return get_environment_status()


@app.get("/api/history")
def read_history() -> list[dict[str, object]]:
    """Return download history items."""

    return history_manager.list_items()


@app.post("/api/download")
def create_download(request: DownloadRequest) -> dict[str, str]:
    """Accept a future download request and return a placeholder status."""

    return ytdlp_service.prepare_download(request)


@app.get("/")
def index() -> FileResponse:
    """Serve the static frontend shell."""

    return FileResponse(STATIC_DIR / "index.html")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=config.host, port=config.port, reload=False)
