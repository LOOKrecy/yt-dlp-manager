from __future__ import annotations

from pydantic import ValidationError
from app.models import AppConfig
from app.path_utils import CONFIG_PATH, ensure_project_dirs
from app.json_store import atomic_write, read


def load_config() -> AppConfig:
    ensure_project_dirs()
    if not CONFIG_PATH.exists():
        config = AppConfig()
        save_config(config)
        return config
    data = read(CONFIG_PATH, {})
    try: return AppConfig(**data)
    except ValidationError: return AppConfig()


def save_config(config: AppConfig) -> AppConfig:
    ensure_project_dirs()
    atomic_write(CONFIG_PATH, config.model_dump())
    return config
