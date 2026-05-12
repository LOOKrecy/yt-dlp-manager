"""Path helpers for repository-local application directories."""

from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
APP_DIR = ROOT_DIR / "app"
STATIC_DIR = APP_DIR / "static"
DOWNLOADS_DIR = ROOT_DIR / "Downloads"
DATA_DIR = ROOT_DIR / "data"
LOGS_DIR = ROOT_DIR / "logs"


def ensure_project_directories() -> None:
    """Create runtime directories if they do not already exist."""

    for directory in (DOWNLOADS_DIR, DATA_DIR, LOGS_DIR):
        directory.mkdir(parents=True, exist_ok=True)
