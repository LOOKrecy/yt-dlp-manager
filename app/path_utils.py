"""Path helpers for repository-local application directories."""

from pathlib import Path
from typing import Literal, TypedDict


ROOT_DIR = Path(__file__).resolve().parent.parent
APP_DIR = ROOT_DIR / "app"
STATIC_DIR = APP_DIR / "static"
BIN_DIR = ROOT_DIR / "bin"
DOWNLOADS_DIR = ROOT_DIR / "Downloads"
DATA_DIR = ROOT_DIR / "data"
LOGS_DIR = ROOT_DIR / "logs"

RUNTIME_DIRECTORIES = {
    "Downloads": DOWNLOADS_DIR,
    "data": DATA_DIR,
    "logs": LOGS_DIR,
}

REQUIRED_TOOLS = {
    "yt-dlp": BIN_DIR / "yt-dlp.exe",
    "ffmpeg": BIN_DIR / "ffmpeg.exe",
    "ffprobe": BIN_DIR / "ffprobe.exe",
}

EnvironmentItemKind = Literal["directory", "file"]


class EnvironmentItem(TypedDict):
    """Status information for a required local path."""

    name: str
    kind: EnvironmentItemKind
    path: str
    exists: bool


class EnvironmentStatus(TypedDict):
    """Grouped status information for required app paths."""

    directories: dict[str, EnvironmentItem]
    tools: dict[str, EnvironmentItem]


def ensure_project_directories() -> None:
    """Create runtime directories if they do not already exist."""

    for directory in RUNTIME_DIRECTORIES.values():
        directory.mkdir(parents=True, exist_ok=True)


def get_environment_status() -> EnvironmentStatus:
    """Return existence checks for runtime directories and bundled tools."""

    ensure_project_directories()

    return {
        "directories": {
            name: {
                "name": name,
                "kind": "directory",
                "path": str(path),
                "exists": path.is_dir(),
            }
            for name, path in RUNTIME_DIRECTORIES.items()
        },
        "tools": {
            name: {
                "name": name,
                "kind": "file",
                "path": str(path),
                "exists": path.is_file(),
            }
            for name, path in REQUIRED_TOOLS.items()
        },
    }
