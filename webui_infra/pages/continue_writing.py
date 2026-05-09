"""V5.0-alpha1 first screen: open the app where the writer left off."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import streamlit as st


@dataclass(frozen=True)
class LastWritingState:
    chapter_number: int
    path: Path
    last_paragraph: str
    modified_at: datetime
    word_count: int
    week_word_count: int


def render_continue_writing(project_dir: Path) -> None:
    state = _read_last_writing_state(project_dir)
    _inject_continue_css()
    if state is None:
        _render_first_run()
        return

    when = _friendly_time(state.modified_at)
    quote = _trim_quote(state.last_paragraph)
    st.markdown(
        f"""
        <div class="continue-card">
          <div class="continue-meta">{when} 你写到这里 ——</div>
          <blockquote>{quote}</blockquote>
          <div class="continue-stats">
            第 {state.chapter_number} 章 · {state.word_count:,} 字 · 本周 {state.week_word_count:,} 字
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col_continue, col_book, _ = st.columns([1.15, 1.15, 4])
    with col_continue:
        if st.button(f"继续写第 {state.chapter_number} 章", type="primary", use_container_width=True):
            st.query_params.update(nav="写作", chapter=str(state.chapter_number))
            st.rerun()
    with col_book:
        if st.button("让我看看全书", use_container_width=True):
            st.query_params.update(nav="写作")
            st.rerun()


def _read_last_writing_state(project_dir: Path) -> LastWritingState | None:
    body_dir = project_dir / "02_正文"
    if not body_dir.exists():
        return None

    candidates: list[Path] = []
    for pattern in ("第*章_定稿.md", "第*章_修订稿.md", "第*章_草稿.md"):
        candidates.extend(path for path in body_dir.glob(pattern) if path.is_file())
    candidates = [path for path in candidates if _read_text(path).strip()]
    if not candidates:
        return None

    latest = max(candidates, key=lambda path: path.stat().st_mtime)
    text = _read_text(latest)
    chapter_number = _chapter_number(latest.name)
    modified_at = datetime.fromtimestamp(latest.stat().st_mtime)
    return LastWritingState(
        chapter_number=chapter_number,
        path=latest,
        last_paragraph=_last_paragraph(text),
        modified_at=modified_at,
        word_count=_zh_word_count(text),
        week_word_count=_week_word_count(candidates),
    )


def _render_first_run() -> None:
    st.markdown(
        """
        <div class="continue-card first-run">
          <div class="continue-meta">还没有故事。</div>
          <blockquote>要不要开始一个？</blockquote>
          <div class="continue-stats">先从故事规格、世界观或第一章章纲开始。</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    col_start, col_notes, _ = st.columns([1.15, 1.15, 4])
    with col_start:
        if st.button("启动一个新故事", type="primary", use_container_width=True):
            st.query_params.update(nav="规划")
            st.rerun()
    with col_notes:
        if st.button("打开笔记", use_container_width=True):
            st.query_params.update(nav="故事圣经")
            st.rerun()


def _inject_continue_css() -> None:
    st.markdown(
        """
        <style>
        .continue-card {
            max-width: 760px;
            padding: 56px 52px 32px;
            margin: 8vh auto 24px;
            background: var(--surface-elevated);
            border: 1px solid var(--border-subtle);
            border-radius: 12px;
            box-shadow: 0 14px 48px rgba(0,0,0,0.06);
        }
        .continue-card blockquote {
            margin: 20px 0 26px;
            padding: 0;
            border: 0;
            font-family: "Noto Serif SC", "Source Han Serif SC", "Songti SC", serif;
            font-size: 24px;
            line-height: 1.85;
            color: var(--text-primary);
        }
        .continue-meta,
        .continue-stats {
            font-size: 13px;
            color: var(--text-muted);
        }
        .first-run blockquote {
            font-size: 28px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _chapter_number(filename: str) -> int:
    match = re.search(r"第(\d{1,4})章", filename)
    return int(match.group(1)) if match else 1


def _last_paragraph(text: str) -> str:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n+", text or "") if part.strip()]
    return paragraphs[-1] if paragraphs else ""


def _trim_quote(text: str, limit: int = 200) -> str:
    compact = re.sub(r"\s+", " ", text or "").strip()
    if len(compact) <= limit:
        return compact
    return compact[-limit:].lstrip("，。；：,.!！？? ") + "…"


def _zh_word_count(text: str) -> int:
    return sum(1 for char in text if "\u4e00" <= char <= "\u9fff")


def _week_word_count(paths: list[Path]) -> int:
    now = datetime.now()
    total = 0
    for path in paths:
        modified_at = datetime.fromtimestamp(path.stat().st_mtime)
        if (now - modified_at).days < 7:
            total += _zh_word_count(_read_text(path))
    return total


def _friendly_time(value: datetime) -> str:
    now = datetime.now()
    if value.date() == now.date():
        prefix = "今天"
    elif (now.date() - value.date()).days == 1:
        prefix = "昨天"
    else:
        prefix = value.strftime("%m月%d日")
    return f"{prefix} {value.strftime('%H:%M')}"
