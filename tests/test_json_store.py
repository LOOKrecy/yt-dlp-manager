import json
import threading

from app.json_store import atomic_write, read, update


def test_atomic_concurrent_updates_do_not_lose_items(tmp_path):
    path = tmp_path / "data.json"; atomic_write(path, {"items": []})
    def append(number):
        update(path, {"items": []}, lambda data: {"items": data["items"] + [number]})
    threads = [threading.Thread(target=append, args=(i,)) for i in range(20)]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    assert sorted(read(path, {})["items"]) == list(range(20))


def test_corrupt_json_is_preserved(tmp_path):
    path = tmp_path / "data.json"; path.write_text("{broken", encoding="utf-8")
    assert read(path, {"safe": True}) == {"safe": True}
    assert list(tmp_path.glob("data.json.corrupt-*"))
    assert not path.exists()
