"""
Multi-book project registry for the novel workbench.

The application code lives at the repository root, while each book is a
file-first project with the same content directories: worldbuilding, outline,
drafts, rolling memory, logs, and project management files.
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REGISTRY_REL = "05_项目管理/book_registry.json"
BOOKS_DIR_REL = "books"
ROOT_BOOK_ID = "root"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def registry_path(app_dir: str | Path) -> Path:
    return Path(app_dir) / REGISTRY_REL


def books_dir(app_dir: str | Path) -> Path:
    return Path(app_dir) / BOOKS_DIR_REL


def ensure_book_registry(app_dir: str | Path) -> dict[str, Any]:
    app_dir = Path(app_dir)
    path = registry_path(app_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    registry = _read_registry(path)
    changed = False

    books = [item for item in registry.get("books", []) if isinstance(item, dict)]
    if not any(item.get("id") == ROOT_BOOK_ID for item in books):
        books.insert(0, _root_book_entry(app_dir))
        changed = True

    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in books:
        book_id = _safe_id(str(item.get("id") or item.get("title") or "book"))
        if not book_id or book_id in seen:
            book_id = _unique_id(seen, book_id or "book")
            changed = True
        seen.add(book_id)
        item["id"] = book_id
        item.setdefault("title", infer_book_title(resolve_book_path(app_dir, item)))
        item.setdefault("path", ".")
        item.setdefault("created_at", now_iso())
        item.setdefault("updated_at", item["created_at"])
        normalized.append(item)

    registry["books"] = normalized
    if registry.get("active_id") not in {item["id"] for item in normalized}:
        registry["active_id"] = ROOT_BOOK_ID
        changed = True
    registry.setdefault("version", 1)
    registry.setdefault("updated_at", now_iso())

    if changed or not path.exists():
        save_book_registry(app_dir, registry)
    return registry


def save_book_registry(app_dir: str | Path, registry: dict[str, Any]) -> Path:
    path = registry_path(app_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    registry["updated_at"] = now_iso()
    path.write_text(json.dumps(registry, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def list_books(app_dir: str | Path) -> list[dict[str, Any]]:
    app_dir = Path(app_dir)
    registry = ensure_book_registry(app_dir)
    rows = []
    for item in registry["books"]:
        path = resolve_book_path(app_dir, item)
        rows.append({
            **item,
            "path": item.get("path", "."),
            "resolved_path": str(path),
            "exists": path.exists(),
            "active": item["id"] == registry.get("active_id"),
            "stats": book_stats(path),
        })
    return rows


def get_active_book(app_dir: str | Path) -> dict[str, Any]:
    app_dir = Path(app_dir)
    registry = ensure_book_registry(app_dir)
    active_id = registry.get("active_id", ROOT_BOOK_ID)
    item = next((book for book in registry["books"] if book["id"] == active_id), registry["books"][0])
    path = resolve_book_path(app_dir, item)
    return {
        **item,
        "resolved_path": str(path),
        "exists": path.exists(),
        "stats": book_stats(path),
    }


def set_active_book(app_dir: str | Path, book_id: str) -> dict[str, Any]:
    app_dir = Path(app_dir)
    registry = ensure_book_registry(app_dir)
    if book_id not in {item["id"] for item in registry["books"]}:
        raise KeyError(f"书籍不存在：{book_id}")
    registry["active_id"] = book_id
    save_book_registry(app_dir, registry)
    return get_active_book(app_dir)


def rename_book(app_dir: str | Path, book_id: str, title: str) -> dict[str, Any]:
    app_dir = Path(app_dir)
    title = (title or "").strip()
    if not title:
        raise ValueError("书名不能为空")

    registry = ensure_book_registry(app_dir)
    item = next((book for book in registry["books"] if book["id"] == book_id), None)
    if item is None:
        raise KeyError(f"书籍不存在：{book_id}")

    item["title"] = title
    item["updated_at"] = now_iso()
    _update_book_info_title(resolve_book_path(app_dir, item), title)
    save_book_registry(app_dir, registry)
    path = resolve_book_path(app_dir, item)
    return {**item, "resolved_path": str(path), "stats": book_stats(path)}


def create_book(
    app_dir: str | Path,
    title: str,
    brief: str = "",
    slug: str = "",
    activate: bool = True,
) -> dict[str, Any]:
    app_dir = Path(app_dir)
    title = (title or "").strip()
    if not title:
        raise ValueError("书名不能为空")

    registry = ensure_book_registry(app_dir)
    base_slug = _safe_slug(slug or title)
    target = _unique_book_path(books_dir(app_dir), base_slug)
    initialize_book_project(app_dir, target, title=title, brief=brief)

    existing_ids = {item["id"] for item in registry["books"]}
    book_id = _unique_id(existing_ids, base_slug)
    entry = {
        "id": book_id,
        "title": title,
        "path": str(target.relative_to(app_dir)).replace("\\", "/"),
        "brief": brief.strip(),
        "created_at": now_iso(),
        "updated_at": now_iso(),
    }
    registry["books"].append(entry)
    if activate:
        registry["active_id"] = book_id
    save_book_registry(app_dir, registry)
    return {**entry, "resolved_path": str(target), "stats": book_stats(target)}


def import_book(
    app_dir: str | Path,
    project_path: str | Path,
    title: str = "",
    activate: bool = True,
) -> dict[str, Any]:
    app_dir = Path(app_dir)
    project_path = Path(project_path).expanduser().resolve()
    if not project_path.exists() or not project_path.is_dir():
        raise FileNotFoundError(f"书籍目录不存在：{project_path}")
    if project_path == app_dir.resolve():
        return set_active_book(app_dir, ROOT_BOOK_ID)

    registry = ensure_book_registry(app_dir)
    existing = next(
        (item for item in registry["books"] if resolve_book_path(app_dir, item) == project_path),
        None,
    )
    if existing:
        if activate:
            registry["active_id"] = existing["id"]
            save_book_registry(app_dir, registry)
        return {**existing, "resolved_path": str(project_path), "stats": book_stats(project_path)}

    title = (title or infer_book_title(project_path)).strip() or project_path.name
    existing_ids = {item["id"] for item in registry["books"]}
    book_id = _unique_id(existing_ids, _safe_slug(title))
    entry = {
        "id": book_id,
        "title": title,
        "path": str(project_path),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "imported": True,
    }
    registry["books"].append(entry)
    if activate:
        registry["active_id"] = book_id
    save_book_registry(app_dir, registry)
    return {**entry, "resolved_path": str(project_path), "stats": book_stats(project_path)}


def remove_book(app_dir: str | Path, book_id: str) -> dict[str, Any]:
    if book_id == ROOT_BOOK_ID:
        raise ValueError("不能从书库移除根项目")
    app_dir = Path(app_dir)
    registry = ensure_book_registry(app_dir)
    removed = next((item for item in registry["books"] if item["id"] == book_id), None)
    if removed is None:
        raise KeyError(f"书籍不存在：{book_id}")
    registry["books"] = [item for item in registry["books"] if item["id"] != book_id]
    if registry.get("active_id") == book_id:
        registry["active_id"] = ROOT_BOOK_ID
    save_book_registry(app_dir, registry)
    return removed


def resolve_book_path(app_dir: str | Path, item: dict[str, Any]) -> Path:
    app_dir = Path(app_dir)
    raw = Path(str(item.get("path") or "."))
    if raw.is_absolute():
        return raw.resolve()
    return (app_dir / raw).resolve()


def initialize_book_project(app_dir: str | Path, target: str | Path, title: str, brief: str = "") -> Path:
    app_dir = Path(app_dir)
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    for rel in [
        "00_世界观/角色档案/AI草案",
        "01_大纲/卷纲",
        "01_大纲/章纲",
        "02_正文",
        "03_滚动记忆/章节记忆",
        "04_审核日志",
        "05_项目管理",
        "06_项目快照",
        "99_回收站",
        "AI审查缓存",
        "logs",
        "prompts",
    ]:
        (target / rel).mkdir(parents=True, exist_ok=True)

    _copy_prompts(app_dir, target)
    _copy_if_exists(app_dir / ".env.example", target / ".env.example")
    _write_if_missing(target / "00_世界观" / "世界观.md", f"# {title} 世界观\n\n（请在此填写本书世界规则、限制、代价和核心场景。）\n")
    _write_if_missing(target / "00_世界观" / "文风档案.md", "# 文风档案\n\n（请在此填写偏好的叙述密度、句式、对白口吻和禁用表达。）\n")
    _write_if_missing(target / "00_世界观" / "角色档案" / "角色模板.md", _character_template())
    _write_if_missing(target / "01_大纲" / "总纲.md", f"# {title} 总纲\n\n（请在此填写主线、阶段目标、人物关系变化和结局方向。）\n")
    _write_if_missing(target / "01_大纲" / "章纲" / "第001章.md", _chapter_outline_template(title))
    _write_if_missing(target / "03_滚动记忆" / "全局摘要.md", "# 全局摘要\n\n（定稿后自动维护，可人工修订。）\n")
    _write_if_missing(target / "03_滚动记忆" / "最近摘要.md", "# 最近章节摘要\n\n（自动保留最近3章，每章约300字；定稿后可人工修订。）\n")
    _write_if_missing(target / "03_滚动记忆" / "伏笔追踪.md", _foreshadow_template())
    _write_if_missing(target / "03_滚动记忆" / "人物状态表.md", "# 人物状态表\n\n（定稿后自动维护；结构化镜像见 `人物状态.json`。）\n")
    _write_if_missing(target / "05_项目管理" / "书籍信息.md", _book_info(title, brief))

    try:
        from project_center import ensure_project_center

        ensure_project_center(target)
    except Exception:
        pass
    return target


def infer_book_title(project_dir: str | Path) -> str:
    project_dir = Path(project_dir)
    info = project_dir / "05_项目管理" / "书籍信息.md"
    if info.exists():
        for line in info.read_text(encoding="utf-8").splitlines():
            if line.startswith("# "):
                title = line.lstrip("# ").strip()
                if title:
                    return title
    spec = project_dir / "05_项目管理" / "故事规格.md"
    if spec.exists():
        text = spec.read_text(encoding="utf-8")
        match = re.search(r"^#\s+(.+?)\s*$", text, flags=re.MULTILINE)
        if match and "故事规格" not in match.group(1):
            return match.group(1).strip()
    return "当前项目" if project_dir.name == "novel" else project_dir.name


def book_stats(project_dir: str | Path) -> dict[str, int]:
    project_dir = Path(project_dir)
    chapter_dir = project_dir / "01_大纲" / "章纲"
    text_dir = project_dir / "02_正文"
    char_dir = project_dir / "00_世界观" / "角色档案"
    return {
        "characters": _count_files(char_dir, "*.md", exclude={"角色模板.md"}),
        "chapter_outlines": _count_files(chapter_dir, "第*章.md"),
        "drafts": _count_files(text_dir, "*_草稿.md"),
        "revised": _count_files(text_dir, "*_修订稿.md"),
        "finals": _count_files(text_dir, "*_定稿.md"),
    }


def _read_registry(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": 1, "active_id": ROOT_BOOK_ID, "books": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"version": 1, "active_id": ROOT_BOOK_ID, "books": []}
    return data if isinstance(data, dict) else {"version": 1, "active_id": ROOT_BOOK_ID, "books": []}


def _root_book_entry(app_dir: Path) -> dict[str, Any]:
    return {
        "id": ROOT_BOOK_ID,
        "title": infer_book_title(app_dir),
        "path": ".",
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "root": True,
    }


def _copy_prompts(app_dir: Path, target: Path) -> None:
    source = app_dir / "prompts"
    dest = target / "prompts"
    if not source.exists():
        return
    for path in source.glob("*.md"):
        _copy_if_exists(path, dest / path.name)


def _copy_if_exists(source: Path, dest: Path) -> None:
    if source.exists() and not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)


def _write_if_missing(path: Path, text: str) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _update_book_info_title(project_dir: Path, title: str) -> None:
    info = project_dir / "05_项目管理" / "书籍信息.md"
    if not info.exists():
        return
    lines = info.read_text(encoding="utf-8").splitlines()
    if lines and lines[0].startswith("# "):
        lines[0] = f"# {title}"
    else:
        lines.insert(0, f"# {title}")
    info.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _book_info(title: str, brief: str) -> str:
    return (
        f"# {title}\n\n"
        f"- 创建时间：{now_iso()}\n"
        f"- 简介：{brief.strip() or '待补充'}\n\n"
        "本目录是一本文学项目的独立工作区，可单独维护世界观、大纲、正文、记忆、日志和快照。\n"
    )


def _character_template() -> str:
    return (
        "# 【角色名】\n\n"
        "## 基本信息\n"
        "- 定位：\n"
        "- 年龄/身份：\n"
        "- 外在特征：\n\n"
        "## 欲望与伤口\n"
        "- 想要：\n"
        "- 害怕：\n"
        "- 秘密：\n\n"
        "## 行为边界\n"
        "- 绝不会说的话：\n"
        "- 典型动作：\n"
    )


def _chapter_outline_template(title: str) -> str:
    return (
        f"# 第001章：{title}开场\n\n"
        "- 视角人物：【主角名】\n"
        "- 字数目标：3000-5000\n"
        "- 时间线：故事第X天\n\n"
        "## 核心事件\n"
        "待补充\n\n"
        "## 情感弧线\n"
        "待补充\n\n"
        "## 伏笔操作\n"
        "- 埋下：无\n"
        "- 收回：无\n\n"
        "## 章末悬念\n"
        "待补充\n\n"
        "## 禁止事项\n"
        "- 不提前揭露核心秘密\n"
    )


def _foreshadow_template() -> str:
    return (
        "# 伏笔追踪表\n\n"
        "| 编号 | 埋入章节 | 伏笔内容 | 状态 | 计划回收章节 | 来源 | 备注 |\n"
        "|------|---------|---------|------|------------|------|------|\n"
    )


def _count_files(path: Path, pattern: str, exclude: set[str] | None = None) -> int:
    if not path.exists():
        return 0
    exclude = exclude or set()
    return sum(1 for item in path.glob(pattern) if item.is_file() and item.name not in exclude)


def _safe_slug(value: str) -> str:
    value = re.sub(r'[<>:"/\\|?*\s]+', "_", value.strip())
    value = re.sub(r"_+", "_", value).strip("._")
    return value[:48] or datetime.now().strftime("book_%Y%m%d_%H%M%S")


def _safe_id(value: str) -> str:
    value = _safe_slug(value).lower()
    value = re.sub(r"[^0-9a-zA-Z_\-\u4e00-\u9fff]+", "_", value)
    return value.strip("_") or "book"


def _unique_id(existing: set[str], base: str) -> str:
    base = _safe_id(base)
    candidate = base
    idx = 2
    while candidate in existing:
        candidate = f"{base}_{idx}"
        idx += 1
    return candidate


def _unique_book_path(parent: Path, slug: str) -> Path:
    parent.mkdir(parents=True, exist_ok=True)
    base = _safe_slug(slug)
    candidate = parent / base
    idx = 2
    while candidate.exists():
        candidate = parent / f"{base}_{idx}"
        idx += 1
    return candidate
