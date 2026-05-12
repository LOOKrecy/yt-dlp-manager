from __future__ import annotations

import os
import platform
import subprocess
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.config_manager import get_config, load_config, save_config
from app.history_manager import HistoryManager
from app.models import (
    ClearHistoryResponse,
    ConfigResponse,
    ConfigUpdateRequest,
    DownloadRequest,
    DownloadResponse,
    EnvironmentResponse,
    FormatRequest,
    FormatResponse,
    HealthResponse,
    HistoryResponse,
    LogResponse,
    OpenPathRequest,
    OpenPathResponse,
    StopDownloadResponse,
)
from app.path_utils import (
    LOGS_DIR,
    STATIC_DIR,
    ensure_project_directories,
    get_environment_status,
)
from app.process_manager import ProcessManager
from app.ytdlp_service import YtDlpService

app_config = get_config()
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


@app.get("/api/config", response_model=ConfigResponse)
def read_config() -> ConfigResponse:
    """Return the persisted frontend configuration."""

    return ConfigResponse(**load_config())


@app.post("/api/config", response_model=ConfigResponse)
def update_config(request: ConfigUpdateRequest) -> ConfigResponse:
    """Persist and return the updated frontend configuration."""

    updated_config = {**load_config(), **request.model_dump(exclude_unset=True)}
    return ConfigResponse(**save_config(updated_config))


@app.get("/api/environment", response_model=EnvironmentResponse)
def read_environment() -> EnvironmentResponse:
    """Return local runtime directory and bundled tool availability."""

    return EnvironmentResponse(**get_environment_status())


@app.post("/api/formats", response_model=FormatResponse)
def read_formats(request: FormatRequest) -> FormatResponse:
    """Return available yt-dlp formats for a URL."""

    try:
        return ytdlp_service.list_formats(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail="yt-dlp executable was not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/download", response_model=DownloadResponse)
def create_download(request: DownloadRequest) -> DownloadResponse:
    """Start a yt-dlp download request."""

    try:
        response = ytdlp_service.prepare_download(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=503, detail="yt-dlp executable was not found") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    history_manager.add_item(
        url=str(response["url"]),
        title="",
        download_dir=request.download_dir,
        output_file=request.output_template,
        mode=request.download_mode,
        format_value=_history_format(request),
        status=str(response["status"]),
        error="",
    )
    return DownloadResponse(**response)


@app.post("/api/download/stop", response_model=StopDownloadResponse)
def stop_download() -> StopDownloadResponse:
    """Stop the current yt-dlp download process."""

    return StopDownloadResponse(**ytdlp_service.stop_download())


@app.get("/api/logs", response_model=LogResponse)
def read_logs(lines: int = Query(default=200, ge=1, le=2000)) -> LogResponse:
    """Return recent lines from the active or latest download log."""

    log_path = process_manager.current_log_path or _latest_log_path()
    if log_path is None:
        return LogResponse(running=process_manager.running)

    return LogResponse(
        log_path=str(log_path),
        running=process_manager.running,
        lines=_tail_file(log_path, lines),
    )


@app.get("/api/history", response_model=HistoryResponse)
def read_history() -> HistoryResponse:
    """Return download history items."""

    return HistoryResponse(items=history_manager.list_items())


@app.post("/api/history/clear", response_model=ClearHistoryResponse)
def clear_history() -> ClearHistoryResponse:
    """Remove all stored download history items."""

    return ClearHistoryResponse(deleted=history_manager.clear())


@app.post("/api/open-file", response_model=OpenPathResponse)
def open_file(request: OpenPathRequest) -> OpenPathResponse:
    """Open a local file in the system-associated application."""

    path = _resolve_path(request.path)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    _open_path(path)
    return OpenPathResponse(path=str(path))


@app.post("/api/open-folder", response_model=OpenPathResponse)
def open_folder(request: OpenPathRequest) -> OpenPathResponse:
    """Open a local folder in the platform file manager."""

    path = _resolve_path(request.path)
    folder_path = path.parent if path.is_file() else path
    if not folder_path.is_dir():
        raise HTTPException(status_code=404, detail="Folder not found")

    _open_path(folder_path)
    return OpenPathResponse(path=str(folder_path))


@app.get("/")
def index() -> FileResponse:
    """Serve the static frontend shell."""

    return FileResponse(STATIC_DIR / "index.html")


def _history_format(request: DownloadRequest) -> str:
    """Return the format value saved into download history."""

    if request.selected_format.strip():
        return request.selected_format.strip()
    if request.download_mode == "audio":
        return request.audio_format.strip() or "mp3"
    if request.download_mode == "video_audio":
        return "bestvideo+bestaudio/best"
    return request.format_mode.strip() or "best"


def _tail_file(path: Path, line_count: int) -> list[str]:
    """Return the last N lines from a UTF-8 text file."""

    try:
        with path.open("r", encoding="utf-8", errors="replace") as log_file:
            return log_file.read().splitlines()[-line_count:]
    except OSError:
        return []


def _latest_log_path() -> Path | None:
    """Return the newest local log file, if one exists."""

    try:
        return max(LOGS_DIR.glob("*.log"), key=lambda path: path.stat().st_mtime)
    except ValueError:
        return None


def _resolve_path(path_value: str) -> Path:
    """Resolve a user-supplied path without requiring it to be absolute."""

    return Path(path_value).expanduser().resolve()


def _open_path(path: Path) -> None:
    """Open a file-system path with the platform default handler."""

    try:
        if platform.system() == "Windows":
            os.startfile(path)  # type: ignore[attr-defined]
            return
        if platform.system() == "Darwin":
            command = ["open", str(path)]
        else:
            command = ["xdg-open", str(path)]

        subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=app_config.host, port=app_config.port, reload=False)
