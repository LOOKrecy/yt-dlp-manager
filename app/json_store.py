from __future__ import annotations

import json
import os
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

_LOCK = threading.RLock()
_notices: list[str] = []


def notices() -> list[str]:
    with _LOCK:
        return list(_notices)


def atomic_write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def update(path: Path, default: Any, operation: Callable[[Any], Any]) -> Any:
    """Single-process read/modify/write transaction. This is not an IPC lock."""
    with _LOCK:
        data = read(path, default)
        result = operation(data)
        atomic_write(path, result)
        return result


def read(path: Path, default: Any) -> Any:
    with _LOCK:
        if not path.exists():
            return default
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = path.with_name(f"{path.name}.corrupt-{stamp}")
            try:
                shutil.move(path, backup)
                _notices.append(f"Повреждённый {path.name} сохранён как {backup.name}: {exc}")
            except OSError:
                _notices.append(f"Не удалось прочитать {path.name}: {exc}")
            return default
