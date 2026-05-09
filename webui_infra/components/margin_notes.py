"""Margin-note helpers for paragraph-level diagnostics."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any


SEVERITY_RANK = {
    "error": 0,
    "warning": 1,
    "info": 2,
    "accepted_by_writer": 9,
}


@dataclass(frozen=True)
class MarginNote:
    note_id: str
    paragraph_index: int
    level: str
    title: str
    detail: str
    quote: str
    suggestion: str
    finding_key: str
    diagnostic_source: str = "quality"
    source_type: str = "finding"


def split_paragraphs(text: str) -> list[str]:
    return [item.strip() for item in re.split(r"\n\s*\n+", text or "") if item.strip()]


def build_margin_notes(
    chapter_text: str,
    quality_report: dict[str, Any] | None,
    limit: int = 5,
) -> list[MarginNote]:
    """Build the most useful page-side notes from quality findings and polish targets."""
    if not quality_report:
        return []
    paragraphs = split_paragraphs(chapter_text)
    if not paragraphs:
        return []

    notes: list[MarginNote] = []
    for idx, row in enumerate(quality_report.get("polish_targets", []) or []):
        if not isinstance(row, dict):
            continue
        quote = str(row.get("原文片段", "") or "")
        title = str(row.get("问题", "") or "精修片段")
        suggestion = str(row.get("改法", "") or "")
        para_idx = _paragraph_index_for_excerpt(paragraphs, quote, row.get("位置"))
        notes.append(MarginNote(
            note_id=f"polish:{idx}:{para_idx}:{title}",
            paragraph_index=para_idx,
            level="warning" if int(row.get("风险", 0) or 0) >= 4 else "info",
            title=title,
            detail=suggestion,
            quote=quote,
            suggestion=suggestion,
            finding_key=f"polish:{title}:{quote[:40]}",
            diagnostic_source="quality",
            source_type="polish",
        ))

    for idx, finding in enumerate(quality_report.get("findings", []) or []):
        if not isinstance(finding, dict):
            continue
        level = str(finding.get("level", "info") or "info")
        if level == "accepted_by_writer":
            continue
        title = str(finding.get("item", "") or "诊断建议")
        detail = str(finding.get("detail", "") or "")
        para_idx = _paragraph_index_for_finding(paragraphs, title, detail)
        quote = _safe_quote(paragraphs, para_idx)
        notes.append(MarginNote(
            note_id=str(finding.get("finding_key") or f"finding:{idx}:{title}"),
            paragraph_index=para_idx,
            level=level,
            title=title,
            detail=detail,
            quote=quote,
            suggestion=detail,
            finding_key=str(finding.get("finding_key") or f"quality:{title}"),
            diagnostic_source=str(finding.get("diagnostic_source") or "quality"),
            source_type="finding",
        ))

    unique: dict[tuple[int, str, str], MarginNote] = {}
    for note in notes:
        key = (note.paragraph_index, note.title, note.quote[:40])
        current = unique.get(key)
        if current is None or _note_sort_key(note) < _note_sort_key(current):
            unique[key] = note
    return sorted(unique.values(), key=_note_sort_key)[:limit]


def _note_sort_key(note: MarginNote) -> tuple[int, int, str]:
    return (SEVERITY_RANK.get(note.level, 3), note.paragraph_index, note.title)


def _paragraph_index_for_finding(paragraphs: list[str], title: str, detail: str) -> int:
    haystack = f"{title} {detail}"
    quoted = re.findall(r"[「“\"']([^」”\"']{4,80})[」”\"']", haystack)
    for excerpt in quoted:
        idx = _paragraph_index_for_excerpt(paragraphs, excerpt, None)
        if idx:
            return idx
    if "章末" in haystack:
        return len(paragraphs)
    if "章首" in haystack or "开头" in haystack:
        return 1
    return 1


def _paragraph_index_for_excerpt(
    paragraphs: list[str],
    excerpt: str,
    position: object,
) -> int:
    pos = str(position or "")
    match = re.search(r"(\d+)", pos)
    if match:
        value = int(match.group(1))
        if 1 <= value <= len(paragraphs):
            return value
    compact_excerpt = _compact(excerpt)
    if compact_excerpt:
        needle = compact_excerpt[: min(len(compact_excerpt), 40)]
        for idx, paragraph in enumerate(paragraphs, start=1):
            if needle and needle in _compact(paragraph):
                return idx
    return 1


def _safe_quote(paragraphs: list[str], paragraph_index: int, limit: int = 80) -> str:
    if not paragraphs:
        return ""
    idx = min(max(paragraph_index, 1), len(paragraphs)) - 1
    value = _compact(paragraphs[idx])
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _compact(text: object) -> str:
    return re.sub(r"\s+", "", str(text or "")).strip()

