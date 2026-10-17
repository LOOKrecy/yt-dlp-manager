from __future__ import annotations

from app.models import HistoryEntry
from app.path_utils import HISTORY_PATH, ensure_project_dirs
from app.json_store import atomic_write, read, update

MAX_HISTORY_ITEMS = 300


def load_history() -> list[HistoryEntry]:
    ensure_project_dirs()
    if not HISTORY_PATH.exists():
        save_history([])
        return []
    data = read(HISTORY_PATH, {"schema_version": 2, "items": []})
    if isinstance(data, dict): data = data.get("items", [])
    entries: list[HistoryEntry] = []
    for item in data if isinstance(data, list) else []:
        try:
            migrated = dict(item); migrated.setdefault("incomplete", not bool(item.get("request_snapshot")))
            entries.append(HistoryEntry(**migrated))
        except Exception:
            continue
    return entries


def save_history(entries: list[HistoryEntry]) -> None:
    ensure_project_dirs()
    atomic_write(HISTORY_PATH, {"schema_version": 2, "items": [entry.model_dump() for entry in entries[:MAX_HISTORY_ITEMS]]})


def add_history(entry: HistoryEntry) -> None:
    def add(data):
        items = data if isinstance(data, list) else data.get("items", [])
        items = [item for item in items if item.get("job_id") != entry.job_id or not entry.job_id]
        return {"schema_version": 2, "items": [entry.model_dump(), *items][:MAX_HISTORY_ITEMS]}
    update(HISTORY_PATH, {"schema_version": 2, "items": []}, add)


def clear_history() -> None:
    save_history([])
