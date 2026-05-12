"""Persistent download history management."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.path_utils import DATA_DIR

HISTORY_FIELDS = (
    "id",
    "datetime",
    "url",
    "title",
    "download_dir",
    "output_file",
    "mode",
    "format",
    "status",
    "error",
)


class HistoryManager:
    """Store lightweight download history entries in a local JSON file."""

    def __init__(self, history_path: Path | None = None) -> None:
        self._history_path = history_path or DATA_DIR / "history.json"
        self._ensure_history_file()

    def list_items(self) -> list[dict[str, Any]]:
        """Return recorded history items, newest first."""

        return list(reversed(self._load_items()))

    def add_item(
        self,
        url: str,
        download_dir: str,
        output_file: str,
        mode: str,
        format_value: str,
        status: str,
        title: str = "",
        error: str = "",
        item_datetime: str | None = None,
    ) -> dict[str, Any]:
        """Append and persist a normalized history entry."""

        item: dict[str, Any] = {
            "id": uuid4().hex,
            "datetime": item_datetime or datetime.now(timezone.utc).isoformat(),
            "url": url,
            "title": title,
            "download_dir": download_dir,
            "output_file": output_file,
            "mode": mode,
            "format": format_value,
            "status": status,
            "error": error,
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

    def _ensure_history_file(self) -> None:
        self._history_path.parent.mkdir(parents=True, exist_ok=True)
        if not self._history_path.exists():
            self._save_items([])

    def _load_items(self) -> list[dict[str, Any]]:
        self._ensure_history_file_for_load()
        try:
            with self._history_path.open("r", encoding="utf-8") as history_file:
                items = json.load(history_file)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return []

        if not isinstance(items, list):
            return []

        return [self._normalize_item(item) for item in items if isinstance(item, dict)]

    def _save_items(self, items: list[dict[str, Any]]) -> None:
        self._history_path.parent.mkdir(parents=True, exist_ok=True)
        normalized_items = [self._normalize_item(item) for item in items]
        with self._history_path.open("w", encoding="utf-8") as history_file:
            json.dump(normalized_items, history_file, ensure_ascii=False, indent=2)
            history_file.write("\n")

    def _ensure_history_file_for_load(self) -> None:
        if not self._history_path.exists():
            self._save_items([])

    def _normalize_item(self, item: dict[str, Any]) -> dict[str, Any]:
        normalized = {field: str(item.get(field, "") or "") for field in HISTORY_FIELDS}
        if not normalized["id"]:
            normalized["id"] = uuid4().hex
        if not normalized["datetime"]:
            normalized["datetime"] = str(
                item.get("created_at", "") or datetime.now(timezone.utc).isoformat()
            )
        if not normalized["mode"]:
            normalized["mode"] = str(item.get("download_mode", "") or "")
        if not normalized["format"]:
            normalized["format"] = str(
                item.get("selected_format", "") or item.get("format_mode", "") or ""
            )
        if not normalized["download_dir"]:
            metadata = item.get("metadata", {})
            normalized["download_dir"] = str(
                metadata.get("download_dir", "") if isinstance(metadata, dict) else ""
            )
        return normalized
