"""Persistent download history management."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.path_utils import DATA_DIR


class HistoryManager:
    """Store lightweight download history entries in a local JSON file."""

    def __init__(self, history_path: Path | None = None) -> None:
        self._history_path = history_path or DATA_DIR / "history.json"

    def list_items(self) -> list[dict[str, Any]]:
        """Return recorded history items, newest first."""

        return list(reversed(self._load_items()))

    def add_item(
        self,
        url: str,
        status: str,
        log_path: str = "",
        pid: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append and persist a history entry."""

        item: dict[str, Any] = {
            "id": uuid4().hex,
            "url": url,
            "status": status,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "log_path": log_path,
            "pid": pid,
            "metadata": metadata or {},
        }
        items = self._load_items()
        items.append(item)
        self._save_items(items)
        return deepcopy(item)

    def clear(self) -> int:
        """Delete all stored history entries and return the number removed."""

        deleted = len(self._load_items())
        self._save_items([])
        return deleted

    def _load_items(self) -> list[dict[str, Any]]:
        if not self._history_path.exists():
            return []

        try:
            with self._history_path.open("r", encoding="utf-8") as history_file:
                items = json.load(history_file)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return []

        if not isinstance(items, list):
            return []

        return [item for item in items if isinstance(item, dict)]

    def _save_items(self, items: list[dict[str, Any]]) -> None:
        self._history_path.parent.mkdir(parents=True, exist_ok=True)
        with self._history_path.open("w", encoding="utf-8") as history_file:
            json.dump(items, history_file, ensure_ascii=False, indent=2)
            history_file.write("\n")
