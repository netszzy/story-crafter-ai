"""File-backed in-app inbox for background job notifications."""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


_LOCK = threading.Lock()


def inbox_path(project_dir: Path) -> Path:
    return Path(project_dir) / "05_项目管理" / "站内信.json"


def read_inbox(project_dir: Path, limit: int = 50) -> list[dict[str, Any]]:
    path = inbox_path(project_dir)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    messages = data if isinstance(data, list) else data.get("messages", [])
    if not isinstance(messages, list):
        return []
    normalized = [msg for msg in messages if isinstance(msg, dict)]
    normalized.sort(key=lambda msg: str(msg.get("created_at", "")), reverse=True)
    return normalized[:limit]


def add_inbox_message(
    project_dir: Path,
    title: str,
    body: str = "",
    *,
    level: str = "info",
    source: str = "background",
) -> dict[str, Any]:
    now = datetime.now().isoformat(timespec="seconds")
    message = {
        "id": uuid.uuid4().hex,
        "created_at": now,
        "read": False,
        "level": level,
        "source": source,
        "title": title.strip() or "后台消息",
        "body": body.strip(),
    }
    with _LOCK:
        messages = read_inbox(project_dir, limit=200)
        messages.insert(0, message)
        messages = messages[:200]
        path = inbox_path(project_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    return message


def mark_inbox_read(project_dir: Path, ids: set[str] | None = None) -> int:
    with _LOCK:
        messages = read_inbox(project_dir, limit=200)
        changed = 0
        for msg in messages:
            if ids is None or str(msg.get("id", "")) in ids:
                if not msg.get("read"):
                    msg["read"] = True
                    changed += 1
        path = inbox_path(project_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(messages, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)
    return changed


def unread_count(project_dir: Path) -> int:
    return sum(1 for msg in read_inbox(project_dir, limit=200) if not msg.get("read"))
