"""Configuration management helpers for yt-dlp-manager.

The module owns the on-disk JSON configuration file and always exposes a
complete configuration dictionary by merging saved values with defaults.
"""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from app.models import AppConfig
from app.path_utils import DATA_DIR, DOWNLOADS_DIR, LOGS_DIR

CONFIG_PATH = DATA_DIR / "config.json"

DEFAULT_CONFIG: dict[str, Any] = {
    "last_url": "",
    "download_dir": "Downloads",
    "proxy_enabled": False,
    "proxy_url": "",
    "cookies_enabled": False,
    "cookies_file": "",
    "section_enabled": False,
    "section_start": "",
    "section_end": "",
    "impersonate_enabled": False,
    "impersonate_target": "",
    "download_mode": "video",
    "audio_format": "mp3",
    "format_mode": "best",
    "selected_format": "",
    "extra_args": "",
    "embed_metadata": True,
    "embed_thumbnail": False,
    "write_subtitles": False,
    "write_auto_subtitles": False,
    "subtitles_language": "",
    "playlist_enabled": False,
    "playlist_start": "",
    "playlist_end": "",
    "overwrite_files": False,
    "restrict_filenames": False,
    "output_template": "%(title)s.%(ext)s",
}


def get_default_config() -> dict[str, Any]:
    """Return an isolated copy of the default configuration."""
    return deepcopy(DEFAULT_CONFIG)


def _merge_with_defaults(config: dict[str, Any]) -> dict[str, Any]:
    """Merge persisted values over defaults while preserving future keys."""
    merged_config = get_default_config()
    merged_config.update(config)
    return merged_config


def ensure_config_file() -> None:
    """Create the data directory and default config file when absent."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not CONFIG_PATH.exists():
        save_config(get_default_config())


def load_config() -> dict[str, Any]:
    """Load config from JSON, falling back to defaults on any invalid data."""
    ensure_config_file()

    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as config_file:
            loaded_config = json.load(config_file)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return get_default_config()

    if not isinstance(loaded_config, dict):
        return get_default_config()

    return _merge_with_defaults(loaded_config)


def save_config(config: dict[str, Any]) -> dict[str, Any]:
    """Persist config as UTF-8 JSON and return the normalized config."""
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    normalized_config = _merge_with_defaults(config)

    with CONFIG_PATH.open("w", encoding="utf-8") as config_file:
        json.dump(normalized_config, config_file, ensure_ascii=False, indent=2)
        config_file.write("\n")

    return normalized_config


def get_config() -> AppConfig:
    """Return the default local-only application configuration."""

    return AppConfig(
        downloads_dir=DOWNLOADS_DIR,
        data_dir=DATA_DIR,
        logs_dir=LOGS_DIR,
    )

