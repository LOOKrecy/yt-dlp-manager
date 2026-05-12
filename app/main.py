from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.config_manager import load_config, save_config
from app.history_manager import clear_history, load_history
from app.models import AppConfig, DownloadRequest, FormatRequest, OpenPathRequest, ToolActionRequest
from app.path_utils import FFMPEG_PATH, STATIC_DIR, YT_DLP_PATH, environment_status, open_with_system, resolve_user_path
from app.process_manager import ProcessManager
from app.ytdlp_service import FALLBACK_IMPERSONATE_TARGETS, build_format_command, parse_formats, quote_command

app = FastAPI(title="Local yt-dlp Manager")
manager = ProcessManager()
event_queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=500)
manager.set_event_queue(event_queue)


@app.on_event("startup")
def startup() -> None:
    load_config()
    environment_status(include_versions=False)


@app.get("/api/config")
def get_config() -> dict:
    return {"config": load_config().model_dump()}


@app.post("/api/config")
def post_config(config: AppConfig) -> dict:
    return {"config": save_config(config).model_dump()}


@app.get("/api/environment")
def get_environment(include_versions: bool = False) -> dict:
    return environment_status(include_versions=include_versions)


@app.get("/api/impersonate-targets")
def impersonate_targets() -> dict:
    if not YT_DLP_PATH.exists():
        return {"targets": FALLBACK_IMPERSONATE_TARGETS, "fallback": True}
    try:
        completed = subprocess.run(
            [str(YT_DLP_PATH), "--list-impersonate-targets"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            shell=False,
        )
    except Exception:
        return {"targets": FALLBACK_IMPERSONATE_TARGETS, "fallback": True}
    if completed.returncode != 0:
        return {"targets": FALLBACK_IMPERSONATE_TARGETS, "fallback": True}
    targets = []
    for line in completed.stdout.splitlines():
        text = line.strip()
        if text and not text.startswith("-") and " " not in text and text.lower() not in {"available", "impersonate", "targets:"}:
            targets.append(text.rstrip(":"))
    return {"targets": targets or FALLBACK_IMPERSONATE_TARGETS, "fallback": not bool(targets)}


@app.post("/api/formats")
def get_formats(request: FormatRequest) -> dict:
    try:
        command = build_format_command(request)
        manager.emit("log", f"Команда запроса форматов: {quote_command(command)}")
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            shell=False,
        )
        raw_output = (completed.stdout or "") + (completed.stderr or "")
        for line in raw_output.splitlines():
            manager.emit("log", line)
        return {
            "success": completed.returncode == 0,
            "formats": [item.model_dump() for item in parse_formats(raw_output)],
            "raw_output": raw_output,
            "command": quote_command(command),
            "error": "" if completed.returncode == 0 else f"yt-dlp -F завершился с кодом {completed.returncode}",
        }
    except ValueError as exc:
        manager.emit("log", f"Ошибка запроса форматов: {exc}")
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/download")
def start_download(request: DownloadRequest) -> dict:
    try:
        config = AppConfig(**request.model_dump(exclude={"url", "last_url"}), last_url=request.url)
        save_config(config)
        job_id = manager.start_download(request)
        return {"success": True, "job_id": job_id}
    except ValueError as exc:
        manager.emit("log", f"Ошибка запуска загрузки: {exc}")
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/download/stop")
def stop_download() -> dict:
    stopped = manager.stop()
    return {"success": stopped, "message": "Download process stopped" if stopped else "Нет активной загрузки"}


@app.get("/api/logs")
def get_logs() -> dict:
    return manager.get_logs()


@app.post("/api/logs/clear")
def clear_logs() -> dict:
    manager.clear_logs()
    return {"success": True}


@app.get("/api/events")
async def events() -> StreamingResponse:
    async def stream():
        while True:
            event = await event_queue.get()
            yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
    return StreamingResponse(stream(), media_type="text/event-stream")


@app.get("/api/history")
def history() -> dict:
    return {"history": [entry.model_dump() for entry in load_history()]}


@app.post("/api/history/clear")
def clear_history_endpoint() -> dict:
    clear_history()
    return {"success": True}


@app.post("/api/open-file")
def open_file(request: OpenPathRequest) -> dict:
    try:
        path = resolve_user_path(request.path, None)
        open_with_system(path)
        return {"success": True}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/open-folder")
def open_folder(request: OpenPathRequest) -> dict:
    try:
        path = resolve_user_path(request.path, None)
        folder = path if path.is_dir() else path.parent
        open_with_system(folder)
        return {"success": True}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/media")
def media(path: str = Query(...)) -> FileResponse:
    resolved = resolve_user_path(path, None)
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail="Файл не найден")
    return FileResponse(resolved)


@app.post("/api/tools")
def tool_action(request: ToolActionRequest) -> dict:
    if request.action == "yt-dlp-version":
        command = [str(YT_DLP_PATH), "--version"]
    elif request.action == "ffmpeg-version":
        command = [str(FFMPEG_PATH), "-version"]
    else:
        command = [str(YT_DLP_PATH), "-U"]
    if not Path(command[0]).exists():
        raise HTTPException(status_code=400, detail=f"Инструмент не найден: {command[0]}")
    completed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120, shell=False)
    output = (completed.stdout or "") + (completed.stderr or "")
    manager.emit("log", f"Команда инструмента: {quote_command(command)}")
    for line in output.splitlines():
        manager.emit("log", line)
    return {"success": completed.returncode == 0, "output": output, "return_code": completed.returncode}


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8765, reload=False)
