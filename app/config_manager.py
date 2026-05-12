from __future__ import annotations

import json
from app.models import AppConfig
from app.path_utils import CONFIG_PATH, ensure_project_dirs


def load_config() -> AppConfig:
    ensure_project_dirs()
    if not CONFIG_PATH.exists():
        config = AppConfig()
        save_config(config)
        return config
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    return AppConfig(**data)


def save_config(config: AppConfig) -> AppConfig:
    ensure_project_dirs()
    CONFIG_PATH.write_text(
        json.dumps(config.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return config
