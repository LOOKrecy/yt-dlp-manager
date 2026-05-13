from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
APP_DIR = PROJECT_ROOT / "app"
STATIC_DIR = APP_DIR / "static"
BIN_DIR = PROJECT_ROOT / "bin"
DOWNLOADS_DIR = PROJECT_ROOT / "Downloads"
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"
CONFIG_PATH = DATA_DIR / "config.json"
HISTORY_PATH = DATA_DIR / "history.json"
YT_DLP_PATH = BIN_DIR / "yt-dlp.exe"
FFMPEG_PATH = BIN_DIR / "ffmpeg.exe"
FFPROBE_PATH = BIN_DIR / "ffprobe.exe"
DENO_PATH = BIN_DIR / "deno.exe"

WINDOWS_FORBIDDEN_CHARS = r'<>:"/\\|?*'
RESERVED_WINDOWS_NAMES = {
    "CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))
}


def ensure_project_dirs() -> None:
    for directory in (BIN_DIR, DOWNLOADS_DIR, DATA_DIR, LOGS_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def resolve_user_path(value: str, default: Path | None = None) -> Path:
    text = (value or "").strip()
    if not text:
        return default or DOWNLOADS_DIR
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def ensure_writable_directory(value: str) -> Path:
    directory = resolve_user_path(value, DOWNLOADS_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    probe = directory / ".write-test"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as exc:
        raise ValueError(f"Папка загрузки недоступна для записи: {directory}") from exc
    return directory


def sanitize_filename_template(value: str) -> str:
    name = (value or "").strip().strip(". ")
    if not name:
        return ""
    cleaned = re.sub(f"[{re.escape(WINDOWS_FORBIDDEN_CHARS)}]", "_", name).strip().strip(".")
    if not cleaned:
        raise ValueError("Имя файла содержит только недопустимые символы")
    stem = cleaned.split(".")[0].upper()
    if stem in RESERVED_WINDOWS_NAMES:
        cleaned = f"_{cleaned}"
    return cleaned[:180]


def build_output_template(download_dir: Path, filename_template: str) -> str:
    safe_name = sanitize_filename_template(filename_template)
    if safe_name:
        return str(download_dir / f"{safe_name}.%(ext)s")
    return str(download_dir / "%(title)s.%(ext)s")


def find_deno_path() -> Path | None:
    if DENO_PATH.exists():
        return DENO_PATH
    deno = shutil.which("deno")
    return Path(deno) if deno else None


def check_tool_version(path: Path, args: list[str], timeout: float = 4.0) -> str:
    if not path.exists():
        return ""
    try:
        completed = subprocess.run(
            [str(path), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
        )
    except Exception as exc:  # noqa: BLE001 - returned to UI as diagnostic text
        return f"error: {exc}"
    output = (completed.stdout or completed.stderr or "").strip().splitlines()
    return output[0] if output else ""


def environment_status(include_versions: bool = False) -> dict[str, Any]:
    ensure_project_dirs()
    tools = {
        "yt_dlp": (YT_DLP_PATH, ["--version"]),
        "ffmpeg": (FFMPEG_PATH, ["-version"]),
        "ffprobe": (FFPROBE_PATH, ["-version"]),
    }
    result: dict[str, Any] = {}
    for key, (path, version_args) in tools.items():
        result[key] = {
            "exists": path.exists(),
            "path": display_path(path),
            "version": check_tool_version(path, version_args) if include_versions else "",
        }
    deno_path = find_deno_path()
    result["deno"] = {
        "exists": deno_path is not None,
        "path": display_path(deno_path) if deno_path else display_path(DENO_PATH),
        "version": check_tool_version(deno_path, ["--version"]) if include_versions and deno_path else "",
        "optional": True,
    }
    try:
        ensure_writable_directory("Downloads")
        downloads_ok = True
        downloads_error = ""
    except ValueError as exc:
        downloads_ok = False
        downloads_error = str(exc)
    result["downloads"] = {"exists": DOWNLOADS_DIR.exists(), "path": display_path(DOWNLOADS_DIR), "writable": downloads_ok, "error": downloads_error}
    result["data"] = {"exists": DATA_DIR.exists(), "path": display_path(DATA_DIR)}
    result["logs"] = {"exists": LOGS_DIR.exists(), "path": display_path(LOGS_DIR)}
    return result


def open_with_system(path: Path) -> None:
    if not path.exists():
        raise ValueError(f"Путь не найден: {path}")
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)], shell=False)
    else:
        subprocess.Popen(["xdg-open", str(path)], shell=False)
