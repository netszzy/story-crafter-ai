"""
Safe chapter maintenance operations.

Deletion is implemented as a move to an in-project recycle bin. This keeps the
UI simple for cleanup while preserving recovery options for accidental deletes.
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path


RECYCLE_DIR = "99_回收站"


def collect_chapter_artifacts(project_dir: Path, chapter_num: int) -> list[Path]:
    ch = f"{chapter_num:03d}"
    candidates = [
        project_dir / "01_大纲" / "章纲" / f"第{ch}章.md",
        project_dir / "01_大纲" / "章纲" / f"第{ch}章_task_card.json",
        project_dir / "01_大纲" / "章纲" / f"第{ch}章_scenes",
        project_dir / "02_正文" / f"第{ch}章_草稿.md",
        project_dir / "02_正文" / f"第{ch}章_修订稿.md",
        project_dir / "02_正文" / f"第{ch}章_定稿.md",
        project_dir / "02_正文" / f"第{ch}章_scenes",
        project_dir / "03_滚动记忆" / "章节记忆" / f"第{ch}章_memory.json",
    ]

    for pattern in [
        f"04_审核日志/第{ch}章*",
        f"02_正文/versions/*第{ch}章*",
        f"04_审核日志/versions/*第{ch}章*",
    ]:
        candidates.extend(project_dir.glob(pattern))

    seen = set()
    artifacts = []
    for path in candidates:
        if not path.exists():
            continue
        resolved = path.resolve()
        if resolved in seen:
            continue
        _assert_inside(project_dir, resolved)
        seen.add(resolved)
        artifacts.append(path)
    return sorted(artifacts, key=lambda item: str(item))


def delete_chapter_to_recycle(project_dir: Path, chapter_num: int, reason: str = "") -> dict:
    artifacts = collect_chapter_artifacts(project_dir, chapter_num)
    if not artifacts:
        return {
            "chapter_number": chapter_num,
            "deleted": [],
            "recycle_dir": "",
            "reason": reason,
        }

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target_root = project_dir / RECYCLE_DIR / f"第{chapter_num:03d}章_{timestamp}"
    target_root.mkdir(parents=True, exist_ok=True)
    moved = []
    for source in artifacts:
        rel = source.relative_to(project_dir)
        target = target_root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(target))
        moved.append(str(rel).replace("\\", "/"))

    manifest = target_root / "delete_manifest.md"
    manifest.write_text(
        "\n".join(
            [
                f"# 第{chapter_num:03d}章删除清单",
                "",
                f"- 时间：{timestamp}",
                f"- 原因：{reason or '未填写'}",
                "",
                "## 已移动文件",
                *[f"- `{item}`" for item in moved],
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return {
        "chapter_number": chapter_num,
        "deleted": moved,
        "recycle_dir": str(target_root.relative_to(project_dir)).replace("\\", "/"),
        "reason": reason,
    }


def _assert_inside(project_dir: Path, target: Path) -> None:
    root = project_dir.resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Refusing to operate outside workspace: {target}") from exc
