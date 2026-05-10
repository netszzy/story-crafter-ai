"""V5.0-rc1 scroll-style whole-book health visualization — three independent dimensions."""
from __future__ import annotations

from dataclasses import dataclass
import html
import json
import re
from pathlib import Path
from typing import Any

import streamlit as st


CREAM = (248, 240, 221)
DEEP_BROWN = (91, 57, 34)
NO_DATA = "#ded6c7"

DIMENSION_LABELS = {
    "engineering": "工程稳健度",
    "literary": "文学密度",
    "style": "风格一致度",
}


@dataclass(frozen=True)
class ScrollHealthChapter:
    chapter_number: int
    score: int | None  # backward-compat alias for engineering
    source: str
    color: str
    summary: str
    worst_diagnostic: str
    keeper_quote: str
    has_draft: bool
    # V5.0-rc1 三维
    score_engineering: int | None = None
    score_literary: int | None = None
    score_style: int | None = None
    color_literary: str = ""
    color_style: str = ""

    def score_for_dimension(self, dim: str) -> int | None:
        return getattr(self, f"score_{dim}", None)

    def color_for_dimension(self, dim: str) -> str:
        if dim == "literary":
            return self.color_literary or self.color
        if dim == "style":
            return self.color_style or self.color
        return self.color


def score_to_scroll_color(score: int | float | None) -> str:
    """Map high scores to cream and weak scores to deep brown, avoiding red/yellow/green."""
    if score is None:
        return NO_DATA
    value = max(0, min(100, int(score)))
    t = 1 - (value / 100)
    r = round(CREAM[0] * (1 - t) + DEEP_BROWN[0] * t)
    g = round(CREAM[1] * (1 - t) + DEEP_BROWN[1] * t)
    b = round(CREAM[2] * (1 - t) + DEEP_BROWN[2] * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def collect_scroll_health(project_dir: str | Path, trends: Any | None = None) -> list[ScrollHealthChapter]:
    root = Path(project_dir)
    if trends is None:
        from dramatic_arc_diagnostics import compute_drama_trends

        trends = compute_drama_trends(root)
    quality_reports = _read_quality_reports(root)
    scores: dict[int, dict[str, Any]] = {}
    for snap in getattr(trends, "chapters", []) or []:
        entry = scores.setdefault(int(snap.chapter_number), {"score": None, "source": ""})
        if not getattr(snap, "is_mock", False):
            entry["score"] = int(getattr(snap, "overall_drama_score", 0) or 0)
            entry["source"] = "戏剧"
    for chapter, report in quality_reports.items():
        if scores.get(chapter, {}).get("score") is None:
            score = report.get("overall_score", report.get("score"))
            if isinstance(score, (int, float)):
                scores.setdefault(chapter, {})["score"] = int(score)
                scores[chapter]["source"] = "质量"

    # V5.0-rc1 三维数据收集
    lit_reports = _read_literary_reports(root)
    voice_flags = _read_voice_flags(root)

    outline_numbers = _outline_numbers(root)
    all_numbers = sorted(set(outline_numbers) | set(scores))
    rows: list[ScrollHealthChapter] = []
    for chapter in all_numbers:
        report = quality_reports.get(chapter, {})
        score = scores.get(chapter, {}).get("score")
        source = scores.get(chapter, {}).get("source") or "暂无"

        # 文学密度：memorable_moments 数归一化
        lit = lit_reports.get(chapter, {})
        memorable_count = len(lit.get("memorable_moments", []))
        score_lit = min(100, int((memorable_count / 5.0) * 100)) if lit else None

        # 风格一致度：flagged_pairs 越少越好
        flagged = voice_flags.get(chapter, 0)
        score_sty = max(0, 100 - flagged * 20) if voice_flags else None

        rows.append(ScrollHealthChapter(
            chapter_number=chapter,
            score=score,
            source=source,
            color=score_to_scroll_color(score),
            summary=_chapter_summary(root, chapter),
            worst_diagnostic=_worst_diagnostic(report),
            keeper_quote=_keeper_quote(root, chapter, report),
            has_draft=_has_chapter_text(root, chapter),
            score_engineering=score,
            score_literary=score_lit,
            score_style=score_sty,
            color_literary=score_to_scroll_color(score_lit),
            color_style=score_to_scroll_color(score_sty),
        ))
    return rows


def weakest_chapter(chapters: list[ScrollHealthChapter], dim: str = "engineering") -> ScrollHealthChapter | None:
    scored = [c for c in chapters if c.score_for_dimension(dim) is not None]
    if not scored:
        return None
    return min(scored, key=lambda c: int(c.score_for_dimension(dim) or 0))


def render_scroll_health(project_dir: str | Path) -> None:
    chapters = collect_scroll_health(project_dir)
    if not chapters:
        st.caption("暂无章节诊断数据。")
        return

    # V5.0-rc1 维度切换
    dim = st.radio(
        "健康维度",
        options=["engineering", "literary", "style"],
        format_func=lambda d: DIMENSION_LABELS[d],
        horizontal=True,
        key="scroll_health_dim",
        label_visibility="collapsed",
    )

    weak = weakest_chapter(chapters, dim)
    dim_label = DIMENSION_LABELS.get(dim, dim)
    if weak:
        ch_num = weak.chapter_number
        if dim == "engineering":
            hint = weak.worst_diagnostic or f"第{ch_num:03d}章工程稳健度最低"
        elif dim == "literary":
            hint = f"第{ch_num:03d}章文学密度最低 — 可记忆瞬间较少"
        else:
            hint = f"第{ch_num:03d}章风格一致度最低 — 角色对白相似度偏高"
        st.markdown(f"**{dim_label}最弱：第 {ch_num:03d} 章**")
        st.caption(hint)

    count = max(1, len(chapters))
    html_parts = [
        """
        <style>
        .v5-scroll-health a[data-tooltip] { position: relative; }
        .v5-scroll-health a[data-tooltip]:hover::after {
            content: attr(data-tooltip);
            position: absolute;
            left: 50%;
            bottom: 14px;
            transform: translateX(-50%);
            z-index: 50;
            min-width: 220px;
            max-width: 320px;
            white-space: pre-line;
            padding: 10px 12px;
            border-radius: 8px;
            border: 1px solid var(--novel-border);
            background: var(--novel-panel);
            color: var(--novel-text);
            box-shadow: 0 10px 28px rgba(36,33,28,0.14);
            font-size: 12px;
            line-height: 1.55;
            pointer-events: none;
        }
        </style>
        """,
        '<div class="v5-scroll-health" '
        'style="display:flex;gap:2px;align-items:stretch;width:100%;margin:10px 0 6px;">'
    ]
    min_width = "4px" if count <= 120 else "2px"
    for row in chapters:
        opacity = "1" if row.has_draft else "0.46"
        color = row.color_for_dimension(dim)
        tooltip = _tooltip(row, dim)
        html_parts.append(
            f'<a href="?nav=写作&chapter={row.chapter_number}" '
            f'aria-label="{html.escape(tooltip, quote=True)}" '
            f'data-tooltip="{html.escape(tooltip, quote=True)}" '
            f'style="display:block;flex:1 1 0;min-width:{min_width};height:8px;'
            f'border-radius:2px;background:{color};opacity:{opacity};'
            f'text-decoration:none;"></a>'
        )
    html_parts.append("</div>")
    html_parts.append(
        '<div style="display:flex;justify-content:space-between;font-size:12px;'
        'color:var(--novel-muted);">'
        '<span>越浅表示越稳</span><span>越深表示更值得回看</span>'
        '</div>'
    )
    st.markdown("".join(html_parts), unsafe_allow_html=True)

    with st.expander("卷轴浮卡数据", expanded=False):
        st.dataframe([
            {
                "章节": f"第{row.chapter_number:03d}章",
                "来源": row.source,
                "工程稳健度": row.score_engineering if row.score_engineering is not None else "暂无",
                "文学密度": row.score_literary if row.score_literary is not None else "暂无",
                "风格一致度": row.score_style if row.score_style is not None else "暂无",
                "一句总结": row.summary,
                "最严重诊断": row.worst_diagnostic,
                "值得保留": row.keeper_quote,
            }
            for row in chapters
        ], use_container_width=True, hide_index=True)


def _read_quality_reports(root: Path) -> dict[int, dict[str, Any]]:
    reports: dict[int, dict[str, Any]] = {}
    log_dir = root / "04_审核日志"
    if not log_dir.exists():
        return reports
    for path in sorted(log_dir.glob("第*章_质量诊断.json")):
        match = re.match(r"第(\d+)章_质量诊断\.json", path.name)
        if not match:
            continue
        try:
            reports[int(match.group(1))] = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
    return reports


def _read_literary_reports(root: Path) -> dict[int, dict[str, Any]]:
    reports: dict[int, dict[str, Any]] = {}
    log_dir = root / "04_审核日志"
    if not log_dir.exists():
        return reports
    for path in sorted(log_dir.glob("第*章_文学批评.json")):
        match = re.match(r"第(\d+)章_文学批评\.json", path.name)
        if not match:
            continue
        try:
            reports[int(match.group(1))] = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
    return reports


def _read_voice_flags(root: Path) -> dict[int, int]:
    flags: dict[int, int] = {}
    log_dir = root / "04_审核日志"
    if not log_dir.exists():
        return flags
    for path in sorted([*log_dir.glob("第*章_声音诊断.json"), *log_dir.glob("第*章_声音指纹.json")]):
        match = re.match(r"第(\d+)章_声音(?:诊断|指纹)\.json", path.name)
        if not match:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            flags[int(match.group(1))] = len(data.get("flagged_pairs", []))
        except Exception:
            continue
    return flags


def _outline_numbers(root: Path) -> list[int]:
    outline_dir = root / "01_大纲" / "章纲"
    if not outline_dir.exists():
        return []
    values = []
    for path in outline_dir.glob("第*章.md"):
        match = re.match(r"第(\d+)章\.md", path.name)
        if match:
            values.append(int(match.group(1)))
    return values


def _has_chapter_text(root: Path, chapter: int) -> bool:
    ch = f"{chapter:03d}"
    body_dir = root / "02_正文"
    return any((body_dir / f"第{ch}章_{kind}.md").exists() for kind in ["草稿", "修订稿", "定稿"])


def _chapter_summary(root: Path, chapter: int) -> str:
    memory = root / "03_滚动记忆" / "最近摘要.md"
    if memory.exists():
        text = memory.read_text(encoding="utf-8")
        pattern = rf"##\s*第0*{chapter}章(?P<body>.*?)(?=\n##\s*第|\Z)"
        match = re.search(pattern, text, flags=re.S)
        if match:
            compact = _compact_md(match.group("body"))
            if compact:
                return _clip(compact, 64)
    quote = _latest_text_excerpt(root, chapter, 64)
    return quote or "暂无摘要"


def _worst_diagnostic(report: dict[str, Any]) -> str:
    findings = report.get("findings", []) or []
    for level in ["error", "warning", "info"]:
        for finding in findings:
            if isinstance(finding, dict) and finding.get("level") == level:
                return str(finding.get("item") or finding.get("detail") or "")
    targets = report.get("polish_targets", []) or []
    if targets and isinstance(targets[0], dict):
        return str(targets[0].get("问题") or targets[0].get("改法") or "")
    return ""


def _keeper_quote(root: Path, chapter: int, report: dict[str, Any]) -> str:
    targets = report.get("polish_targets", []) or []
    if targets and isinstance(targets[-1], dict):
        quote = str(targets[-1].get("原文片段") or "").strip()
        if quote:
            return _clip(quote, 80)
    return _latest_text_excerpt(root, chapter, 80)


def _latest_text_excerpt(root: Path, chapter: int, limit: int) -> str:
    ch = f"{chapter:03d}"
    for kind in ["定稿", "修订稿", "草稿"]:
        path = root / "02_正文" / f"第{ch}章_{kind}.md"
        if path.exists():
            paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", path.read_text(encoding="utf-8")) if p.strip()]
            if paragraphs:
                return _clip(_compact_md(paragraphs[-1]), limit)
    return ""


def _tooltip(row: ScrollHealthChapter, dim: str = "engineering") -> str:
    score = row.score_for_dimension(dim)
    score_str = "暂无诊断" if score is None else f"{DIMENSION_LABELS.get(dim, dim)}:{score}"
    parts = [f"第{row.chapter_number:03d}章", score_str]
    if row.summary:
        parts.append(row.summary)
    if row.worst_diagnostic:
        parts.append("诊断：" + row.worst_diagnostic)
    if row.keeper_quote:
        parts.append("保留：" + row.keeper_quote)
    return "\n".join(parts)


def _compact_md(text: str) -> str:
    value = re.sub(r"[#>*_`|~-]+", " ", text or "")
    return re.sub(r"\s+", " ", value).strip()


def _clip(text: str, limit: int) -> str:
    value = re.sub(r"\s+", " ", text or "").strip()
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"
