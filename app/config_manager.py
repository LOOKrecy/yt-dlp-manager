"""Configuration loading for the local yt-dlp manager app."""

from app.models import AppConfig
from app.path_utils import DATA_DIR, DOWNLOADS_DIR, LOGS_DIR


def get_config() -> AppConfig:
    """Return the default local-only application configuration."""

    return AppConfig(
        downloads_dir=DOWNLOADS_DIR,
        data_dir=DATA_DIR,
        logs_dir=LOGS_DIR,
    )
