"""
V5.0-beta2 风格法庭。

裁决工程诊断和文学批评之间的冲突：硬约束继续进入必修链路，可能
误伤氛围、内省、残响和未说之语的建议进入 contested。
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from project_archive import archive_existing
from novel_schemas import (
    LiteraryView,
    StyleCourtDecision,
    StyleCourtIssue,
    model_to_json,
)


PROTECTED_MODES = {"interior", "atmosphere", "bridge"}
HARD_TERMS = [
    "forbidden", "禁止", "任务卡", "核心事件", "逻辑", "矛盾", "断裂", "占位符", "时间线", "人物崩塌",
]
SOFT_LITERARY_TERMS = [
    "冲突", "主动性", "agency", "身体", "动作", "追读", "钩子", "抓力", "情绪身体化",
    "压力", "代价", "选择", "对白比例", "可感细节", "文气质地",
]


def adjudicate(
    project_dir: Path,
    chapter_num: int,
    quality_report: dict[str, Any] | None = None,
    literary_view: LiteraryView | dict[str, Any] | None = None,
    task_card: Any | None = None,
) -> StyleCourtDecision:
    """把质量 finding 和文学风险分流为 confirmed / contested。"""
    project_dir = Path(project_dir)
    view = _normalize_literary_view(literary_view)
    meta = _resolve_chapter_meta(project_dir, chapter_num, quality_report, task_card)
    mode = str(meta.get("chapter_mode", "") or "").lower()
    style_profile = str(meta.get("style_profile", "") or "")
    protected = mode in PROTECTED_MODES and bool(view and view.cannot_be_quantified)

    confirmed: list[StyleCourtIssue] = []
    contested: list[StyleCourtIssue] = []

    for finding in _active_findings(quality_report):
        issue = _issue_from_finding(finding)
        if _is_hard_issue(finding):
            confirmed.append(StyleCourtIssue(
                source="quality",
                issue=issue,
                reason="任务卡、forbidden、逻辑连续性或其他硬约束仍需优先处理。",
                finding_key=str(finding.get("finding_key", "")),
            ))
        elif protected and _is_soft_literary_issue(finding):
            contested.append(StyleCourtIssue(
                source="quality",
                issue=issue,
                reason="本章处在氛围/内省保护口径，且文学批评标记为不可量化；该建议可能误伤克制、残响或未说之语。",
                finding_key=str(finding.get("finding_key", "")),
            ))
        else:
            confirmed.append(StyleCourtIssue(
                source="quality",
                issue=issue,
                reason="未触发文学保护冲突，可作为普通编辑参考。",
                finding_key=str(finding.get("finding_key", "")),
            ))

    if view is not None:
        for risk in view.literary_risks:
            if not risk:
                continue
            if _is_mock_caveat(risk):
                continue
            contested.append(StyleCourtIssue(
                source="literary",
                issue=risk,
                reason="文学批评层提示该改法可能损伤文本的克制、氛围、残响或人物遮蔽。",
            ))

    priorities = _literary_priorities(view)
    return StyleCourtDecision(
        chapter_number=chapter_num,
        chapter_mode=mode,
        style_profile=style_profile,
        confirmed_issues=_dedupe_issues(confirmed),
        contested_issues=_dedupe_issues(contested),
        literary_priorities=priorities,
        cannot_be_quantified=bool(view and view.cannot_be_quantified),
        is_mock=bool(view and view.is_mock),
    )


def write_style_court(project_dir: Path, decision: StyleCourtDecision) -> tuple[Path, Path]:
    project_dir = Path(project_dir)
    ch = f"{decision.chapter_number:03d}"
    log_dir = project_dir / "04_审核日志"
    json_path = log_dir / f"第{ch}章_风格法庭.json"
    md_path = log_dir / f"第{ch}章_风格法庭.md"
    log_dir.mkdir(parents=True, exist_ok=True)
    archive_existing(json_path)
    archive_existing(md_path)
    json_path.write_text(model_to_json(decision) + "\n", encoding="utf-8")
    md_path.write_text(style_court_to_markdown(decision), encoding="utf-8")
    return md_path, json_path


def read_style_court(project_dir: Path, chapter_num: int) -> StyleCourtDecision | None:
    path = Path(project_dir) / "04_审核日志" / f"第{chapter_num:03d}章_风格法庭.json"
    if not path.exists():
        return None
    try:
        return StyleCourtDecision.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValidationError):
        return None


def style_court_to_markdown(decision: StyleCourtDecision) -> str:
    lines = [
        f"# 第{decision.chapter_number:03d}章 风格法庭",
        "",
        f"- 章节模式：{decision.chapter_mode or '未指定'}",
        f"- 风格档案：{decision.style_profile or '未指定'}",
        f"- 不可量化保护：{'是' if decision.cannot_be_quantified else '否'}",
        f"- Mock：{'是' if decision.is_mock else '否'}",
        "",
        "## Confirmed Issues",
    ]
    if decision.confirmed_issues:
        lines.extend(f"- [{item.source}] {item.issue}：{item.reason}" for item in decision.confirmed_issues)
    else:
        lines.append("- 暂无。")

    lines += ["", "## Contested Issues"]
    if decision.contested_issues:
        lines.extend(f"- [{item.source}] {item.issue}：{item.reason}" for item in decision.contested_issues)
    else:
        lines.append("- 暂无。")

    lines += ["", "## Literary Priorities"]
    if decision.literary_priorities:
        lines.extend(f"- {item}" for item in decision.literary_priorities)
    else:
        lines.append("- 暂无。")
    return "\n".join(lines).strip() + "\n"


def contested_to_reservations(decision: StyleCourtDecision | None) -> list[dict[str, str]]:
    """把 contested issues 转为 EditorMemo reservations 的输入形态。"""
    if decision is None:
        return []
    rows: list[dict[str, str]] = []
    for item in decision.contested_issues:
        rows.append({
            "diagnostic_source": item.source or "style_court",
            "rejected_advice": item.issue,
            "writer_reason": item.reason,
            "finding_key": item.finding_key,
        })
    return rows


def _normalize_literary_view(view: LiteraryView | dict[str, Any] | None) -> LiteraryView | None:
    if view is None:
        return None
    if isinstance(view, LiteraryView):
        return view
    try:
        return LiteraryView.model_validate(view)
    except ValidationError:
        return None


def _resolve_chapter_meta(
    project_dir: Path,
    chapter_num: int,
    quality_report: dict[str, Any] | None,
    task_card: Any | None,
) -> dict[str, str]:
    alignment = (quality_report or {}).get("task_card_alignment", {}) if isinstance(quality_report, dict) else {}
    mode = str(alignment.get("chapter_mode", "") or "")
    style_profile = str(alignment.get("style_profile", "") or "")
    if task_card is not None:
        mode = mode or str(getattr(task_card, "chapter_mode", "") or "")
        style_profile = style_profile or str(getattr(task_card, "style_profile", "") or "")
    if not mode:
        try:
            from structured_store import read_task_card

            card = read_task_card(project_dir, chapter_num)
            if card is not None:
                mode = str(card.chapter_mode or "")
                style_profile = style_profile or str(card.style_profile or "")
        except Exception:
            pass
    return {"chapter_mode": mode or "plot", "style_profile": style_profile}


def _active_findings(report: dict[str, Any] | None) -> list[dict[str, Any]]:
    """从报告 dict 中提取 active findings，委托 quality_diagnostics 统一过滤。"""
    from quality_diagnostics import _active_findings as _filter

    if not isinstance(report, dict):
        return []
    rows = report.get("findings", [])
    if not isinstance(rows, list):
        return []
    return _filter(rows)


def _issue_from_finding(finding: dict[str, Any]) -> str:
    item = str(finding.get("item", "") or "未命名诊断")
    detail = str(finding.get("detail", "") or "")
    return f"{item}：{detail}" if detail else item


def _is_hard_issue(finding: dict[str, Any]) -> bool:
    text = _issue_from_finding(finding)
    level = str(finding.get("level", "") or "").lower()
    return level == "error" or any(term in text for term in HARD_TERMS)


def _is_soft_literary_issue(finding: dict[str, Any]) -> bool:
    text = _issue_from_finding(finding)
    return any(term in text for term in SOFT_LITERARY_TERMS)


def _literary_priorities(view: LiteraryView | None) -> list[str]:
    if view is None:
        return []
    rows: list[str] = []
    for moment in view.memorable_moments[:3]:
        quote = moment.quote or "未标注原文"
        rows.append(f"保护可记忆瞬间：「{quote}」")
    for item in view.unsaid_tension[:2]:
        rows.append(f"保留未说之语：{item}")
    for item in view.reader_residue[:2]:
        rows.append(f"保留读者残响：{item}")
    return _dedupe_strings(rows)[:6]


def _dedupe_issues(items: list[StyleCourtIssue]) -> list[StyleCourtIssue]:
    seen: set[str] = set()
    unique: list[StyleCourtIssue] = []
    for item in items:
        key = f"{item.source}:{item.issue[:80]}:{item.finding_key}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _dedupe_strings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for item in items:
        key = item[:100]
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _is_mock_caveat(text: str) -> bool:
    return str(text).startswith("[Mock]") and "不应把本占位结果" in str(text)
