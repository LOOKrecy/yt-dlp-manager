"""Minimal download history service placeholder."""

from typing import Any


class HistoryManager:
    """In-memory history manager used until persistent storage is added."""

    def __init__(self) -> None:
        self._items: list[dict[str, Any]] = []

    def list_items(self) -> list[dict[str, Any]]:
        """Return recorded history items."""

        return list(self._items)
