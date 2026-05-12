from __future__ import annotations

import json
from app.models import HistoryEntry
from app.path_utils import HISTORY_PATH, ensure_project_dirs

MAX_HISTORY_ITEMS = 300


def load_history() -> list[HistoryEntry]:
    ensure_project_dirs()
    if not HISTORY_PATH.exists():
        save_history([])
        return []
    try:
        data = json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = []
    entries: list[HistoryEntry] = []
    for item in data if isinstance(data, list) else []:
        try:
            entries.append(HistoryEntry(**item))
        except Exception:
            continue
    return entries


def save_history(entries: list[HistoryEntry]) -> None:
    ensure_project_dirs()
    HISTORY_PATH.write_text(
        json.dumps([entry.model_dump() for entry in entries[:MAX_HISTORY_ITEMS]], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def add_history(entry: HistoryEntry) -> None:
    entries = load_history()
    entries.insert(0, entry)
    save_history(entries)


def clear_history() -> None:
    save_history([])
