"""
V3.1 样本池管理 — 持久化高画面感段落，支持锁定/排除。

与 prompt_assembly.inject_prose_samples 协同：
- 定稿诊断后自动把高分段落写入 05_项目管理/prose_sample_pool.json
- inject_prose_samples 从池中优先选取（锁定条目 > 高分条目）
- WebUI 可标记锁定（始终注入）或排除（永不注入）
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from novel_schemas import ProseSampleEntry

POOL_REL = "05_项目管理/prose_sample_pool.json"
POOL_CAP = 50
ACTION_VERBS = [
    "推", "按", "拿", "放", "走", "停", "看", "抬", "低", "转", "握",
    "敲", "递", "靠", "坐", "站", "笑", "咬", "摸", "拧", "摁", "拉",
    "关", "开", "躲", "追", "退", "伸", "拍", "擦",
]


def _pool_path(project_dir: Path) -> Path:
    return project_dir / POOL_REL


def load_pool(project_dir: Path) -> list[ProseSampleEntry]:
    """读取样本池 JSON，文件缺失返回空列表。"""
    path = _pool_path(project_dir)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    entries: list[ProseSampleEntry] = []
    for item in data if isinstance(data, list) else []:
        try:
            entries.append(ProseSampleEntry(**item))
        except Exception:
            continue
    return entries


def save_pool(project_dir: Path, entries: list[ProseSampleEntry]) -> Path:
    """写入样本池 JSON（含 versions 备份）。"""
    path = _pool_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(
        [entry.model_dump() for entry in entries],
        ensure_ascii=False,
        indent=2,
    )
    path.write_text(raw + "\n", encoding="utf-8")
    return path


# ─────────────────────────────────────────────────────────────────────────────
# 段落抽取（复用 prompt_assembly 的过滤逻辑）
# ─────────────────────────────────────────────────────────────────────────────

def _normalize(text: str) -> str:
    return " ".join(line.strip() for line in (text or "").splitlines() if line.strip())


def _has_dialogue_or_action(text: str) -> bool:
    # “ = LEFT DOUBLE QUOTATION MARK, ” = RIGHT DOUBLE QUOTATION MARK
    if re.search(r"[“”\"「」『』]", text):
        return True
    return bool(re.search(
        r"(推|按|拿|放|走|停|看|抬|低|转|握|敲|递|靠|坐|站|笑|咬|摸|拧|摁|拉|关|开|躲|追|退|伸|拍|擦)",
        text,
    ))


def _split_paragraphs(text: str) -> list[str]:
    blocks = re.split(r"\n\s*\n+", text.strip())
    if len(blocks) <= 1:
        blocks = text.splitlines()
    return [_normalize(block) for block in blocks if _normalize(block)]


def _candidate_paragraphs(text: str) -> list[str]:
    paragraphs: list[str] = []
    for paragraph in _split_paragraphs(text):
        if paragraph.startswith("#"):
            continue
        length = len(re.sub(r"\s+", "", paragraph))
        if length < 80 or length > 220:
            continue
        if not _has_dialogue_or_action(paragraph):
            continue
        paragraphs.append(paragraph)
    return paragraphs


# ─────────────────────────────────────────────────────────────────────────────
# 核心 API
# ─────────────────────────────────────────────────────────────────────────────

def populate_from_chapter(
    project_dir: Path,
    chapter_num: int,
    chapter_text: str,
    cinematic_score: int,
    is_mock: bool = False,
) -> int:
    """从章节正文抽取高分段落加入样本池。返回新增条目数。"""
    if is_mock or cinematic_score < 80:
        return 0

    pool = load_pool(project_dir)
    existing_texts = {_normalize(entry.text) for entry in pool}
    chapter_texts: set[str] = set()

    added = 0
    for paragraph in _candidate_paragraphs(chapter_text):
        norm = _normalize(paragraph)
        if norm in existing_texts or norm in chapter_texts:
            continue
        chapter_texts.add(norm)

        # 用章节自身 cinematic_score 作为此段落的评分
        entry = ProseSampleEntry(
            text=_clip(paragraph),
            source_chapter=chapter_num,
            technique_label=f"第{chapter_num:03d}章高画面感片段",
            cinematic_score=cinematic_score,
        )
        pool.append(entry)
        added += 1

    if not added:
        return 0

    # 移除同一章节的旧条目，只保留新抽取的 + 其他章节的
    deduped: list[ProseSampleEntry] = []
    for entry in pool:
        if entry.source_chapter == chapter_num:
            # 只保留本轮新增的（已在 chapter_texts 中登记）
            if _normalize(entry.text) in chapter_texts:
                deduped.append(entry)
            # 旧条目丢弃
        else:
            deduped.append(entry)

    # 截断到 POOL_CAP，优先保留锁定和高分
    deduped.sort(key=lambda e: (-e.locked, -e.cinematic_score, e.added_at))
    deduped = deduped[:POOL_CAP]

    save_pool(project_dir, deduped)
    return added


def get_pool_samples(
    pool: list[ProseSampleEntry],
    max_count: int,
    seen: set[str],
) -> list[tuple[str, str, str]]:
    """从池中选择样本，返回 [(来源标签, 技巧标签, 段落文本), ...]。

    选取优先级：锁定条目(按分降序) → 普通条目(按分降序)
    排除 excluded=True 的条目。
    """
    locked = [e for e in pool if e.locked and not e.excluded]
    normal = [e for e in pool if not e.locked and not e.excluded]

    locked.sort(key=lambda e: -e.cinematic_score)
    normal.sort(key=lambda e: -e.cinematic_score)

    result: list[tuple[str, str, str]] = []
    for entry in locked + normal:
        if len(result) >= max_count:
            break
        norm = _normalize(entry.text)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        label = entry.technique_label or f"第{entry.source_chapter:03d}章"
        source = "样本池(锁定)" if entry.locked else "样本池"
        result.append((source, label, _clip(norm)))

    return result


# ─────────────────────────────────────────────────────────────────────────────
# 锁定 / 排除 toggle
# ─────────────────────────────────────────────────────────────────────────────

def _update_flag(project_dir: Path, index: int, field: str, value: bool) -> list[ProseSampleEntry]:
    pool = load_pool(project_dir)
    if 0 <= index < len(pool):
        setattr(pool[index], field, value)
    save_pool(project_dir, pool)
    return pool


def lock_sample(project_dir: Path, index: int) -> list[ProseSampleEntry]:
    return _update_flag(project_dir, index, "locked", True)


def unlock_sample(project_dir: Path, index: int) -> list[ProseSampleEntry]:
    return _update_flag(project_dir, index, "locked", False)


def exclude_sample(project_dir: Path, index: int) -> list[ProseSampleEntry]:
    return _update_flag(project_dir, index, "excluded", True)


def include_sample(project_dir: Path, index: int) -> list[ProseSampleEntry]:
    return _update_flag(project_dir, index, "excluded", False)


# ─────────────────────────────────────────────────────────────────────────────
# helpers
# ─────────────────────────────────────────────────────────────────────────────

def _clip(text: str, limit: int = 220) -> str:
    return text if len(text) <= limit else text[:limit].rstrip() + "…"
