"""
Long-form structure helpers for V2.0.

The project has a strong chapter workflow; this module adds a lightweight
volume/act layer so global constraints can reach chapter planning and prose
generation without forcing a database.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


VOLUME_DIR_REL = "01_大纲/卷纲"
VOLUME_FILE_PATTERN = re.compile(r"第(\d+)卷\.md$")
CHAPTER_RANGE_PATTERN = re.compile(r"(?:章节范围|覆盖章节|章节)\s*[：:]\s*(?:第)?(\d{1,4})\s*(?:章)?\s*[-~—至到]\s*(?:第)?(\d{1,4})")


@dataclass
class VolumePlan:
    volume_number: int
    title: str
    path: Path
    chapter_start: int | None = None
    chapter_end: int | None = None
    summary: str = ""

    @property
    def rel_id(self) -> str:
        return f"volume_{self.volume_number:02d}"


def volume_dir(project_dir: Path) -> Path:
    return Path(project_dir) / VOLUME_DIR_REL


def default_volume_template(volume_number: int, chapter_start: int, chapter_end: int) -> str:
    return f"""# 第{volume_number:02d}卷：待命名

## 卷定位
- 章节范围：{chapter_start:03d}-{chapter_end:03d}
- 叙事功能：本卷在全书中的结构任务，例如开局立局、关系破局、技术升级、代价反噬或终局收束。
- 读者承诺：本卷必须兑现的爽点、情感推进、谜题推进或文明尺度选择。

## 核心冲突
- 外部压力：
- 内在压力：
- 关系压力：

## 角色弧线
- 主角：
- 关键配角：
- 对手/阻碍：

## 伏笔预算
- 本卷必须埋下：
- 本卷必须回收：
- 禁止提前揭露：

## 节奏目标
- 开端：
- 中段：
- 结尾：

## 卷末状态
- 技术/规则变化：
- 人物关系变化：
- 未解决问题：
"""


def ensure_volume_plan(project_dir: Path, volume_number: int, chapter_start: int, chapter_end: int) -> Path:
    target = volume_dir(project_dir) / f"第{volume_number:02d}卷.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        target.write_text(default_volume_template(volume_number, chapter_start, chapter_end), encoding="utf-8")
    return target


def ensure_default_volumes(project_dir: Path, count: int = 3, chapters_per_volume: int = 50) -> list[Path]:
    paths = []
    for idx in range(1, count + 1):
        start = (idx - 1) * chapters_per_volume + 1
        end = idx * chapters_per_volume
        paths.append(ensure_volume_plan(project_dir, idx, start, end))
    return paths


def list_volume_plans(project_dir: Path) -> list[VolumePlan]:
    d = volume_dir(project_dir)
    if not d.exists():
        return []
    plans = []
    for path in sorted(d.glob("第*卷.md")):
        match = VOLUME_FILE_PATTERN.match(path.name)
        if not match:
            continue
        text = path.read_text(encoding="utf-8")
        number = int(match.group(1))
        title = _extract_title(text) or f"第{number:02d}卷"
        start, end = _extract_chapter_range(text)
        summary = _first_nonempty_block(text, limit=420)
        plans.append(VolumePlan(number, title, path, start, end, summary))
    return plans


def active_volume_for_chapter(project_dir: Path, chapter_num: int) -> VolumePlan | None:
    for plan in list_volume_plans(project_dir):
        if plan.chapter_start is not None and plan.chapter_end is not None:
            if plan.chapter_start <= chapter_num <= plan.chapter_end:
                return plan
    plans = list_volume_plans(project_dir)
    return plans[0] if plans else None


def volume_axis_block(project_dir: Path, limit: int = 3500) -> str:
    plans = list_volume_plans(project_dir)
    if not plans:
        return ""
    parts = []
    for plan in plans:
        chapter_range = ""
        if plan.chapter_start is not None and plan.chapter_end is not None:
            chapter_range = f"（第{plan.chapter_start:03d}-{plan.chapter_end:03d}章）"
        parts.append(f"### {plan.title}{chapter_range}\n\n{plan.summary}")
    block = "\n\n".join(parts).strip()
    if len(block) > limit:
        return block[:limit].rstrip() + "\n\n…（卷/幕结构已截断，完整内容见 01_大纲/卷纲/）"
    return block


def active_volume_block(project_dir: Path, chapter_num: int, limit: int = 2200) -> str:
    plan = active_volume_for_chapter(project_dir, chapter_num)
    if not plan:
        return ""
    text = plan.path.read_text(encoding="utf-8").strip()
    if len(text) > limit:
        text = text[:limit].rstrip() + "\n\n…（当前卷纲已截断）"
    return f"## 当前卷/幕约束：{plan.title}\n\n{text}"


def infer_chapter_num(text: str) -> int | None:
    match = re.search(r"第0*(\d{1,4})章", text)
    return int(match.group(1)) if match else None


def _extract_title(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("#"):
            return line.lstrip("#").strip()
    return ""


def _extract_chapter_range(text: str) -> tuple[int | None, int | None]:
    match = CHAPTER_RANGE_PATTERN.search(text)
    if not match:
        return None, None
    start, end = int(match.group(1)), int(match.group(2))
    return min(start, end), max(start, end)


def _first_nonempty_block(text: str, limit: int) -> str:
    cleaned = "\n".join(line.rstrip() for line in text.splitlines() if line.strip())
    return cleaned[:limit].rstrip() + ("…" if len(cleaned) > limit else "")
