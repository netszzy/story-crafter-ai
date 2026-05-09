"""写作台 V5.0-beta1 — 单栏稿纸

从 webui.py 的 page_generate() 懒加载调用，避免顶层循环 import。
"""
from __future__ import annotations

import difflib
import json
from datetime import datetime
import streamlit as st
from pathlib import Path

# ── 工具/状态（从 webui_infra，无循环依赖） ──────────────────────────────────
from webui_infra.state import is_llm_running, set_llm_running, reset_chapter_buffers
from webui_infra.components.keyboard import (
    apply_shortcut_to_state,
    render_keyboard_shortcuts,
    shortcut_cheatsheet,
)
from webui_infra.components.margin_notes import MarginNote, build_margin_notes

# ── webui.py 工具函数（懒加载保证无循环 import） ────────────────────────────
from webui import (
    PROJECT_DIR,
    read_file, write_file, ch_str, parse_chapter_num, word_count, list_md,
    latest_chapter_text, chapter_state, chapter_status, prose_model_label, action_model_label,
    render_chapter_status_card,
    _render_smart_action_panel,
    _render_writing_assist,
    _render_assist_candidate_adoption,
    _render_delete_chapter_controls,
    _scene_workspace,
    _run_pipeline,
    _run_feedback_revision,
    _run_finalize,
    apply_runtime_mode,
    run_writing_assist,
    extract_adoptable_assist_text,
    run_beautify_assist_package,
    run_hook_assist_package,
    _md_editor,
    _set_llm_running,
    _is_llm_running,
    _start_llm_background_job,
    _widget_key,
    _save_review,
)


# ─────────────────────────────────────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────────────────────────────────────

def render() -> None:
    """写作台主入口，由 webui.page_generate() 调用。"""
    _inject_writing_surface_css()
    _consume_shortcut_query()
    render_keyboard_shortcuts()

    outlines = list_md("01_大纲/章纲")
    if not outlines:
        mock_mode = st.session_state.get("_global_mock", False)
        st.info("还没有章纲。可以直接从这里开始，AI 会先创建第 001 章章纲，再进入写作。")
        if st.button(
            "AI 创建第 001 章并进入写作",
            type="primary",
            use_container_width=True,
            disabled=is_llm_running(st.session_state),
            key="writing_create_first_chapter_outline",
        ):
            _run_chapter_autopilot(1, mock_mode)
            st.rerun()
        return

    mock_mode = st.session_state.get("_global_mock", False)

    # 默认定位到首个未定稿章节
    default_idx = _default_chapter_index(outlines)
    # 热力图等深度链接跳转：从 query_params 传入的目标章节
    qp_chapter = st.session_state.pop("_query_chapter", None)
    if qp_chapter is not None:
        target_name = f"第{qp_chapter:03d}章"
        for i, name in enumerate(outlines):
            if name.startswith(target_name):
                default_idx = i
                break
    if "_writing_outline_sel_pending" in st.session_state:
        st.session_state["_writing_outline_sel"] = st.session_state.pop("_writing_outline_sel_pending")
    prev = st.session_state.get("_writing_outline_sel")
    init_idx = outlines.index(prev) if prev in outlines else default_idx

    selected = _render_writing_toolbar(outlines, init_idx)
    chapter_num = parse_chapter_num(selected) if selected else None
    if not chapter_num:
        return

    # 章节切换时清空编辑缓冲
    prev_num = st.session_state.get("_writing_current_num")
    if prev_num != chapter_num:
        reset_chapter_buffers(st.session_state)
        st.session_state["_writing_current_num"] = chapter_num

    ch = ch_str(chapter_num)
    state = chapter_state(chapter_num)
    _llm_lock = is_llm_running(st.session_state)

    _render_ai_autopilot(chapter_num, ch, mock_mode, _llm_lock)

    if st.session_state.get("_writing_command_panel", False):
        _render_command_panel(chapter_num, ch, state, mock_mode, _llm_lock)

    if st.session_state.get("_writing_ai_panel", False):
        with st.expander("AI 助手", expanded=True):
            _render_writing_assist(chapter_num, mock_mode, key_prefix="top_ai_panel")

    _render_draft_view(chapter_num, ch, state, mock_mode, _llm_lock)

    if st.session_state.get("_writing_diag_drawer", False):
        _render_diagnostics_drawer(chapter_num, ch, mock_mode)


def _consume_shortcut_query() -> None:
    shortcut = st.query_params.get("shortcut")
    if not shortcut:
        return
    action = apply_shortcut_to_state(st.session_state, shortcut)
    if action:
        st.session_state["_writing_last_shortcut"] = action
    try:
        del st.query_params["shortcut"]
    except Exception:
        pass


def _render_writing_toolbar(outlines: list[str], init_idx: int) -> str | None:
    focus = bool(st.session_state.get("_writing_focus_mode", False))
    if focus:
        st.markdown('<div class="v5-focus-pill">专注写作中</div>', unsafe_allow_html=True)

    with st.container():
        st.markdown('<div class="v5-writing-toolbar">', unsafe_allow_html=True)
        col_chapter, col_title, col_more = st.columns(
            [1.25, 3.5, 0.75],
            gap="small",
        )
        with col_chapter:
            selected = st.selectbox(
                "章节",
                outlines,
                index=init_idx,
                key="_writing_outline_sel",
                label_visibility="collapsed",
                format_func=lambda name: f"{chapter_status(parse_chapter_num(name))}  {name}",
            )
        chapter_num = parse_chapter_num(selected) if selected else None
        with col_title:
            title = _chapter_title(chapter_num, selected or "") if chapter_num else "写作台"
            st.markdown(f"<div class='v5-toolbar-title'>{title}</div>", unsafe_allow_html=True)
        with col_more:
            if st.button("更多", key="v5_toggle_command", use_container_width=True):
                _toggle_state("_writing_command_panel")
        st.markdown("</div>", unsafe_allow_html=True)

    # 风格 / 模式指示器（紧贴工具栏下方）
    if chapter_num:
        _render_style_mode_indicator(chapter_num)

    if st.session_state.get("_writing_search_open", False):
        st.text_input("搜索当前章节", key="_writing_search_query", placeholder="输入关键词，稿纸仍保留在下方")
    return selected


def _render_style_mode_indicator(chapter_num: int) -> None:
    """写作工具栏下方：显示当前生效的风格档案、章节模式、节奏。"""
    from style_profiles import (
        get_style_profile, resolve_style_profile_name, style_profile_options,
    )

    profile_name = resolve_style_profile_name(PROJECT_DIR, chapter_num)
    sp = get_style_profile(profile_name, project_dir=PROJECT_DIR) if profile_name else None
    profile_display = sp.display_name if sp else (profile_name or "未设定")

    # 读任务卡获取 chapter_mode / pacing
    task_path = PROJECT_DIR / "01_大纲" / "章纲" / f"第{chapter_num:03d}章_task_card.json"
    mode = "plot"
    pacing = "normal"
    card_style = ""
    if task_path.exists():
        try:
            data = json.loads(task_path.read_text(encoding="utf-8"))
            mode = data.get("chapter_mode", "plot")
            pacing = data.get("pacing", "normal")
            card_style = data.get("style_profile", "")
        except Exception:
            pass

    mode_labels = {
        "plot": "剧情推进", "bridge": "过渡桥接", "interior": "内心内省",
        "atmosphere": "氛围渲染", "epilogue": "尾声余韵",
    }
    pacing_labels = {"fast": "快节奏", "normal": "常规", "slow_burn": "慢燃"}

    # 风格档案来源标记
    source_note = ""
    if card_style and card_style == profile_name:
        source_note = "（本章设定）"
    elif profile_name and not card_style:
        source_note = "（项目默认）"

    st.markdown(
        f'<div style="display:flex;gap:12px;align-items:center;padding:2px 0 8px;'
        f'font-size:12px;color:var(--novel-muted);">'
        f'<span>风格：<strong style="color:var(--novel-text);">{profile_display}</strong>'
        f'  {source_note}</span>'
        f'<span>|</span>'
        f'<span>模式：<strong style="color:var(--novel-text);">{mode_labels.get(mode, mode)}</strong></span>'
        f'<span>|</span>'
        f'<span>节奏：<strong style="color:var(--novel-text);">{pacing_labels.get(pacing, pacing)}</strong></span>'
        f'</div>',
        unsafe_allow_html=True,
    )


def _render_ai_autopilot(chapter_num: int, ch: str, mock_mode: bool, llm_lock: bool) -> None:
    from workflow_advisor import chapter_flow, ACTION_LABELS

    flow = chapter_flow(PROJECT_DIR, chapter_num)
    rec = flow["recommendation"]
    action = rec.get("action", "")
    if action == "complete":
        next_chapter = _next_chapter_number(chapter_num)
        target = chapter_num + 1
        if next_chapter:
            c1, c2 = st.columns([1.4, 1], gap="medium")
            c1.success("本章闭环已完成。")
            if c2.button(
                f"AI 推进第 {next_chapter:03d} 章",
                type="primary",
                use_container_width=True,
                disabled=llm_lock,
                key=f"writing_enter_next_{ch}",
            ):
                _select_chapter(next_chapter)
                _run_chapter_autopilot(next_chapter, mock_mode)
                st.rerun()
        else:
            c1, c2 = st.columns([1.4, 1], gap="medium")
            c1.success("本章闭环已完成。下一章还没有章纲。")
            if c2.button(
                f"AI 推进第 {target:03d} 章",
                type="primary",
                use_container_width=True,
                disabled=llm_lock,
                key=f"writing_create_next_{ch}",
            ):
                _select_chapter(target)
                _run_chapter_autopilot(target, mock_mode)
                st.rerun()
        return

    disabled = llm_lock
    next_step = ACTION_LABELS.get(action, action)

    col_ai, col_manual = st.columns([1.5, 1], gap="medium")

    with col_ai:
        checkpoint = _read_autopilot_checkpoint(chapter_num)
        if checkpoint.get("last_status") in {"paused", "recovered"}:
            st.caption(f"断点：{checkpoint.get('last_action', '')} · {checkpoint.get('last_message', '')[:90]}")
        if st.button(
            "AI 自动推进当前章",
            type="primary",
            use_container_width=True,
            disabled=disabled,
            key=f"writing_autopilot_{ch}",
            help=f"下一步：{next_step}",
        ):
            _run_chapter_autopilot(chapter_num, mock_mode)
            st.rerun()
        if action == "edit_outline":
            st.caption("下一步：AI 会先在本页补全章纲，再继续生成任务卡、场景和正文。")
        else:
            label = action_model_label(action, mock_mode)
            st.caption(f"下一步：{next_step}{' · ' + label if label else ''}")

    with col_manual:
        _render_manual_actions(chapter_num, ch, flow, llm_lock)


def _render_manual_actions(chapter_num: int, ch: str, flow: dict, llm_lock: bool) -> None:
    """需要人工裁决的操作：定稿、更新记忆、切章。与 AI 推进并列显示。"""
    artifacts = flow.get("artifacts", {})
    has_any = artifacts.get("draft") or artifacts.get("revised") or artifacts.get("final")
    has_final = artifacts.get("final", False)
    memory_updated = artifacts.get("memory_updated", False)

    # 定稿按钮：有草稿/修订稿即可定稿
    if has_any and not has_final:
        with st.form(key=f"writing_finalize_form_{ch}", border=False):
            confirmed = st.checkbox("确认定稿（覆盖已有定稿）", key=f"writing_confirm_finalize_{ch}")
            submitted = st.form_submit_button(
                "定稿",
                use_container_width=True,
                disabled=llm_lock,
            )
            if submitted:
                if not confirmed:
                    st.warning("请先勾选「确认定稿（覆盖已有定稿）」再提交")
                else:
                    has_revised = bool(read_file(f"02_正文/第{ch}章_修订稿.md").strip())
                    src = f"02_正文/第{ch}章_修订稿.md" if has_revised else f"02_正文/第{ch}章_草稿.md"
                    write_file(f"02_正文/第{ch}章_定稿.md", read_file(src))
                    st.success("已保存为定稿草案，长期记忆尚未更新。")
                    st.rerun()

    # 更新记忆按钮：有定稿且记忆未更新
    elif has_final and not memory_updated:
        with st.form(key=f"writing_finalize_mem_form_{ch}", border=False):
            confirmed_mem = st.checkbox("确认更新长期记忆", key=f"writing_confirm_mem_{ch}")
            submitted = st.form_submit_button(
                "定稿并更新记忆",
                use_container_width=True,
                disabled=llm_lock,
            )
            if submitted:
                if not confirmed_mem:
                    st.warning("请先勾选「确认更新长期记忆」再提交")
                else:
                    _run_finalize(chapter_num, mock=False)
                    st.rerun()

    # 切到下一章
    next_chapter = _next_chapter_number(chapter_num)
    if next_chapter:
        if st.button(
            f"切到第 {next_chapter} 章",
            use_container_width=True,
            key=f"writing_next_chapter_{ch}",
        ):
            if _select_chapter(next_chapter):
                st.rerun()
            st.warning(f"第 {next_chapter} 章章纲不存在")


def _next_chapter_number(current: int) -> int | None:
    """返回下一章的章号，不存在则返回 None。"""
    outlines = list_md("01_大纲/章纲")
    target = f"第{current + 1:03d}章"
    for name in outlines:
        if name.startswith(target):
            return current + 1
    return None


def _select_chapter(chapter_num: int) -> bool:
    target = f"第{chapter_num:03d}章"
    for name in list_md("01_大纲/章纲"):
        if name.startswith(target):
            st.session_state["_writing_outline_sel_pending"] = name
            return True
    return False


def _run_integrated_chapter_outline_job(
    chapter_num: int,
    mock: bool,
    *,
    source_chapter: int | None = None,
) -> None:
    def work(cancel_event):
        if cancel_event.is_set():
            return None
        apply_runtime_mode(mock)
        messages: list[str] = []
        try:
            messages = _generate_or_adopt_chapter_outline(chapter_num, mock, source_chapter=source_chapter)
            _record_autopilot_checkpoint(chapter_num, "outline_ready", "done", messages[-1] if messages else "")
        except Exception as exc:
            _record_autopilot_checkpoint(chapter_num, "outline_ready", "paused", str(exc))
            recovered = _adopt_latest_chapter_outline_draft(chapter_num)
            if recovered:
                messages = recovered + [f"AI 接口中断，但已从最近草案恢复第 {chapter_num:03d} 章章纲。"]
            else:
                messages = [f"第 {chapter_num:03d} 章章纲生成暂停：{_short_error(exc)}"]
        return {"chapter": chapter_num, "messages": messages}

    def done(result):
        if isinstance(result, dict):
            _select_chapter(int(result.get("chapter", chapter_num)))
            for message in result.get("messages", []):
                st.success(message)

    _start_llm_background_job(
        f"第{chapter_num:03d}章 AI 章纲生成",
        work,
        eta_seconds=90,
        on_success=done,
    )


def _generate_or_adopt_chapter_outline(
    chapter_num: int,
    mock: bool,
    *,
    source_chapter: int | None = None,
) -> list[str]:
    from planning_assist import generate_chapter_outline_draft

    recovered = _adopt_latest_chapter_outline_draft(chapter_num)
    if recovered:
        return recovered

    brief = _chapter_outline_auto_brief(chapter_num, source_chapter)
    draft_path = generate_chapter_outline_draft(PROJECT_DIR, chapter_num, brief, mock=mock)
    return _adopt_chapter_outline_draft(chapter_num, draft_path)


def _adopt_latest_chapter_outline_draft(chapter_num: int) -> list[str]:
    ch = ch_str(chapter_num)
    formal = PROJECT_DIR / "01_大纲" / "章纲" / f"第{ch}章.md"
    if formal.exists() and formal.read_text(encoding="utf-8").strip():
        return []
    draft_dir = PROJECT_DIR / "01_大纲" / "章纲" / "AI草案"
    if not draft_dir.exists():
        return []
    drafts = sorted(
        draft_dir.glob(f"第{ch}章章纲草案_*.md"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not drafts:
        return []
    return _adopt_chapter_outline_draft(chapter_num, drafts[0], recovered=True)


def _adopt_chapter_outline_draft(chapter_num: int, draft_path: Path, *, recovered: bool = False) -> list[str]:
    content = draft_path.read_text(encoding="utf-8")
    adopted = extract_adoptable_assist_text(content).strip() or content.strip()
    if not adopted:
        raise RuntimeError("AI 没有返回可采纳的章纲内容")
    ch = ch_str(chapter_num)
    write_file(f"01_大纲/章纲/第{ch}章.md", adopted.rstrip() + "\n")
    prefix = "已从最近草案恢复并采纳" if recovered else "已在写作页生成并采纳"
    return [f"第 {ch} 章章纲{prefix}。"]


def _outline_review_cache_key(chapter_num: int) -> str:
    return f"outline_章纲_{chapter_num}"


def _volume_review_cache_key(volume_name: str) -> str:
    return f"outline_卷纲_{Path(volume_name).name}"


def _active_volume_name_for_chapter(chapter_num: int) -> str:
    from long_structure import active_volume_for_chapter

    plan = active_volume_for_chapter(PROJECT_DIR, chapter_num)
    if plan:
        return plan.path.name
    volume_number = max(1, ((chapter_num - 1) // 50) + 1)
    return f"第{volume_number:02d}卷.md"


def _ensure_volume_file_for_chapter(chapter_num: int) -> str:
    from long_structure import active_volume_for_chapter, ensure_volume_plan

    plan = active_volume_for_chapter(PROJECT_DIR, chapter_num)
    if plan:
        return plan.path.name
    volume_number = max(1, ((chapter_num - 1) // 50) + 1)
    start = (volume_number - 1) * 50 + 1
    end = volume_number * 50
    path = ensure_volume_plan(PROJECT_DIR, volume_number, start, end)
    return path.name


def _volume_generated_marker_path(volume_name: str) -> Path:
    return PROJECT_DIR / "AI审查缓存" / f"outline_outline_卷纲_{Path(volume_name).name}_generated.json"


def _volume_improve_marker_path(volume_name: str) -> Path:
    return PROJECT_DIR / "AI审查缓存" / f"outline_outline_卷纲_{Path(volume_name).name}_improved.json"


def _mark_volume_generated(volume_name: str) -> None:
    _write_volume_marker(_volume_generated_marker_path(volume_name), volume_name)


def _mark_volume_improved(volume_name: str) -> None:
    _write_volume_marker(_volume_improve_marker_path(volume_name), volume_name)


def _write_volume_marker(marker_path: Path, volume_name: str) -> None:
    volume_file = PROJECT_DIR / "01_大纲" / "卷纲" / Path(volume_name).name
    content = volume_file.read_text(encoding="utf-8") if volume_file.exists() else ""
    import hashlib

    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text(
        json.dumps(
            {
                "volume": Path(volume_name).name,
                "volume_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _adopt_latest_volume_outline_draft(volume_name: str) -> list[str]:
    draft_dir = PROJECT_DIR / "01_大纲" / "卷纲" / "AI草案"
    if not draft_dir.exists():
        return []
    stem = Path(volume_name).stem
    drafts = sorted(
        list(draft_dir.glob(f"{stem}卷纲草案_*.md")) + list(draft_dir.glob(f"{stem}卷纲改稿_*.md")),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not drafts:
        return []
    return _adopt_volume_outline_draft(volume_name, drafts[0], recovered=True)


def _adopt_volume_outline_draft(volume_name: str, draft_path: Path, *, recovered: bool = False) -> list[str]:
    content = draft_path.read_text(encoding="utf-8")
    adopted = extract_adoptable_assist_text(content).strip() or content.strip()
    if not adopted:
        raise RuntimeError(f"{Path(volume_name).stem}卷纲没有返回可采纳内容")
    target_name = Path(volume_name).name
    write_file(f"01_大纲/卷纲/{target_name}", adopted.rstrip() + "\n")
    _mark_volume_generated(target_name)
    prefix = "已从最近草案恢复并采纳" if recovered else "已在写作页生成并采纳"
    return [f"{Path(target_name).stem}卷纲{prefix}。"]


def _generate_or_adopt_volume_outline(chapter_num: int, mock: bool) -> list[str]:
    from planning_assist import generate_volume_outline_draft

    volume_name = _ensure_volume_file_for_chapter(chapter_num)
    recovered = _adopt_latest_volume_outline_draft(volume_name)
    if recovered:
        return recovered
    brief = _volume_outline_auto_brief(chapter_num, volume_name)
    draft_path = generate_volume_outline_draft(PROJECT_DIR, volume_name, brief, mock=mock)
    return _adopt_volume_outline_draft(volume_name, draft_path)


def _run_volume_outline_review(chapter_num: int, mock: bool, volume_name: str | None = None) -> list[str]:
    from planning_assist import review_volume_outline

    target = Path(volume_name or _active_volume_name_for_chapter(chapter_num)).name
    review = review_volume_outline(PROJECT_DIR, target, mock=mock)
    if not review.strip():
        raise RuntimeError(f"{Path(target).stem}卷纲审查没有返回内容")
    _save_review("outline", _volume_review_cache_key(target), review)
    return [f"{Path(target).stem}卷纲审查已完成。"]


def _run_volume_outline_improve(chapter_num: int, mock: bool, volume_name: str | None = None) -> list[str]:
    from planning_assist import improve_volume_outline

    target = Path(volume_name or _active_volume_name_for_chapter(chapter_num)).name
    review_path = PROJECT_DIR / "AI审查缓存" / f"outline_outline_卷纲_{target}.md"
    review = review_path.read_text(encoding="utf-8") if review_path.exists() else ""
    if not review.strip():
        raise RuntimeError(f"{Path(target).stem}还没有可用的卷纲审查意见")
    improved_path = improve_volume_outline(PROJECT_DIR, target, review, mock=mock)
    content = improved_path.read_text(encoding="utf-8")
    adopted = extract_adoptable_assist_text(content).strip() or content.strip()
    if not adopted:
        raise RuntimeError(f"{Path(target).stem}卷纲改稿没有返回可采纳内容")
    write_file(f"01_大纲/卷纲/{target}", adopted.rstrip() + "\n")
    _mark_volume_improved(target)
    return [f"{Path(target).stem}卷纲已按审查意见改稿并采纳。"]


def _volume_outline_auto_brief(chapter_num: int, volume_name: str) -> str:
    ch = ch_str(chapter_num)
    chapter_outline = read_file(f"01_大纲/章纲/第{ch}章.md")
    global_outline = read_file("01_大纲/总纲.md")
    return (
        f"请补全 {Path(volume_name).stem} 卷纲，使它能约束第 {ch} 章及同卷后续章节。"
        "输出应包含卷定位、核心冲突、角色弧线、伏笔预算、节奏目标和卷末状态；"
        "保留明确章节范围，避免只写泛泛方向。\n\n"
        f"## 当前第 {ch} 章章纲\n{chapter_outline[:2200] or '暂无章纲内容。'}\n\n"
        f"## 总纲节选\n{global_outline[:2200] or '暂无总纲。'}"
    )


def _outline_improve_marker_path(chapter_num: int) -> Path:
    return PROJECT_DIR / "AI审查缓存" / f"outline_outline_章纲_{chapter_num}_improved.json"


def _mark_outline_improved(chapter_num: int) -> None:
    ch = ch_str(chapter_num)
    outline = read_file(f"01_大纲/章纲/第{ch}章.md")
    import hashlib

    marker_path = _outline_improve_marker_path(chapter_num)
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text(
        json.dumps(
            {
                "chapter": chapter_num,
                "outline_hash": hashlib.sha256(outline.encode("utf-8")).hexdigest(),
                "updated_at": datetime.now().isoformat(timespec="seconds"),
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _run_chapter_outline_review(chapter_num: int, mock: bool) -> list[str]:
    from planning_assist import review_chapter_outline

    ch = ch_str(chapter_num)
    review = review_chapter_outline(PROJECT_DIR, chapter_num, mock=mock)
    if not review.strip():
        raise RuntimeError(f"第 {ch} 章章纲审查没有返回内容")
    _save_review("outline", _outline_review_cache_key(chapter_num), review)
    return [f"第 {ch} 章章纲审查已完成。"]


def _run_chapter_outline_improve(chapter_num: int, mock: bool) -> list[str]:
    from planning_assist import improve_chapter_outline

    ch = ch_str(chapter_num)
    review_path = PROJECT_DIR / "AI审查缓存" / f"outline_outline_章纲_{chapter_num}.md"
    review = review_path.read_text(encoding="utf-8") if review_path.exists() else ""
    if not review.strip():
        raise RuntimeError(f"第 {ch} 章还没有可用的章纲审查意见")
    improved_path = improve_chapter_outline(PROJECT_DIR, chapter_num, review, mock=mock)
    content = improved_path.read_text(encoding="utf-8")
    adopted = extract_adoptable_assist_text(content).strip() or content.strip()
    if not adopted:
        raise RuntimeError(f"第 {ch} 章章纲改稿没有返回可采纳内容")
    write_file(f"01_大纲/章纲/第{ch}章.md", adopted.rstrip() + "\n")
    _mark_outline_improved(chapter_num)
    return [f"第 {ch} 章章纲已按审查意见改稿并采纳。"]


def _review_and_improve_chapter_outline(chapter_num: int, mock: bool) -> list[str]:
    messages = []
    messages.extend(_run_chapter_outline_review(chapter_num, mock))
    messages.extend(_run_chapter_outline_improve(chapter_num, mock))
    return messages


def _autopilot_checkpoint_path(chapter_num: int) -> Path:
    return PROJECT_DIR / "05_项目管理" / "AI推进断点" / f"第{chapter_num:03d}章.json"


def _record_autopilot_checkpoint(chapter_num: int, action: str, status: str, message: str = "") -> None:
    path = _autopilot_checkpoint_path(chapter_num)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    history = data.setdefault("history", [])
    history.append({
        "time": datetime.now().isoformat(timespec="seconds"),
        "action": action,
        "status": status,
        "message": message,
    })
    data.update({
        "chapter": chapter_num,
        "last_action": action,
        "last_status": status,
        "last_message": message,
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    })
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_autopilot_checkpoint(chapter_num: int) -> dict:
    path = _autopilot_checkpoint_path(chapter_num)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _short_error(exc: Exception) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    text = " ".join(text.split())
    return text[:500]


def _chapter_outline_auto_brief(chapter_num: int, source_chapter: int | None) -> str:
    previous_num = source_chapter if source_chapter is not None else chapter_num - 1
    previous_text = ""
    if previous_num > 0:
        prev_ch = ch_str(previous_num)
        _, previous_text = latest_chapter_text(prev_ch)
    previous_tail = previous_text.strip()[-1800:] if previous_text else "暂无上一章正文。"
    return (
        f"请为第 {chapter_num:03d} 章生成可直接进入写作流水线的章纲。"
        "不要只给方向，要包含本章目标、冲突、关键场景、人物变化、伏笔推进和章末钩子。"
        "如果上一章已经完成，请自然承接上一章结尾。\n\n"
        f"## 上一章尾段/上下文\n{previous_tail}"
    )


def _run_chapter_autopilot(chapter_num: int, mock: bool) -> None:
    def work(cancel_event):
        from workflow_advisor import chapter_flow

        apply_runtime_mode(mock)
        messages: list[str] = []
        terminal_actions = {"complete"}
        for _ in range(14):
            if cancel_event.is_set():
                return _autopilot_result(chapter_num, "paused", messages, "已取消本轮推进。")
            flow = chapter_flow(PROJECT_DIR, chapter_num)
            rec = flow["recommendation"]
            action = rec.get("action", "")
            if action in terminal_actions:
                messages.append(_autopilot_stop_message(action, rec))
                _record_autopilot_checkpoint(chapter_num, action, "done", messages[-1])
                status = "complete" if action == "complete" else "paused"
                return _autopilot_result(chapter_num, status, messages)
            try:
                step_messages = _execute_autopilot_action(chapter_num, action, rec, mock)
                messages.extend(step_messages)
                _record_autopilot_checkpoint(
                    chapter_num,
                    action,
                    "done",
                    step_messages[-1] if step_messages else "已完成",
                )
            except Exception as exc:
                recovered = []
                if action == "edit_outline":
                    recovered = _adopt_latest_chapter_outline_draft(chapter_num)
                elif action == "generate_volume_outline":
                    recovered = _adopt_latest_volume_outline_draft(rec.get("volume_name") or _active_volume_name_for_chapter(chapter_num))
                if recovered:
                    messages.extend(recovered)
                    _record_autopilot_checkpoint(chapter_num, action, "recovered", recovered[-1])
                    continue
                msg = f"{action} 暂停：{_short_error(exc)}。已保存断点，下次点击会从这里继续。"
                messages.append(msg)
                _record_autopilot_checkpoint(chapter_num, action, "paused", msg)
                return _autopilot_result(chapter_num, "paused", messages)
            if action == "feedback_revise":
                messages.append("AI 已生成一版修订稿；请在稿纸上看过后再决定是否定稿。")
                _record_autopilot_checkpoint(chapter_num, action, "paused", messages[-1])
                return _autopilot_result(chapter_num, "paused", messages)
        messages.append("已连续推进多步。为避免过度自动改写，先停在当前状态等你查看。")
        return _autopilot_result(chapter_num, "advanced", messages)

    def done(result):
        messages = result.get("messages", []) if isinstance(result, dict) else (result or [])
        for message in messages:
            st.success(message)
        if isinstance(result, dict) and result.get("next_label"):
            st.info(f"下一步：{result['next_label']}")

    _start_llm_background_job(
        f"第{chapter_num}章 AI 自动推进",
        work,
        eta_seconds=240,
        on_success=done,
    )


def _autopilot_result(chapter_num: int, status: str, messages: list[str], extra_message: str = "") -> dict:
    from workflow_advisor import chapter_flow

    flow = chapter_flow(PROJECT_DIR, chapter_num)
    rec = flow.get("recommendation", {})
    next_label = "" if status == "complete" else str(rec.get("label", "")).strip()
    result_messages = list(messages)
    if extra_message:
        result_messages.append(extra_message)
    if next_label:
        result_messages.append(f"下一步：{next_label}")
    title_status = "已完成" if status == "complete" else "本轮推进结束"
    return {
        "status": status,
        "chapter": chapter_num,
        "messages": result_messages,
        "next_action": rec.get("action", ""),
        "next_label": next_label,
        "inbox_title": f"第{chapter_num}章 AI 自动推进{title_status}",
    }


def _execute_autopilot_action(chapter_num: int, action: str, rec: dict, mock: bool) -> list[str]:
    ch = ch_str(chapter_num)
    messages: list[str] = []
    if action == "generate_volume_outline":
        messages.extend(_generate_or_adopt_volume_outline(chapter_num, mock))
    elif action == "review_volume_outline":
        messages.extend(_run_volume_outline_review(chapter_num, mock, rec.get("volume_name")))
    elif action == "improve_volume_outline":
        messages.extend(_run_volume_outline_improve(chapter_num, mock, rec.get("volume_name")))
    elif action == "edit_outline":
        messages.extend(_generate_or_adopt_chapter_outline(chapter_num, mock))
    elif action == "review_outline":
        messages.extend(_run_chapter_outline_review(chapter_num, mock))
    elif action == "improve_outline":
        messages.extend(_run_chapter_outline_improve(chapter_num, mock))
    elif action == "generate_task_card":
        from llm_router import LLMRouter
        from prompt_assembly import build_axis_context
        from structured_store import sync_task_card_from_outline

        llm = LLMRouter(project_dir=PROJECT_DIR)
        card = sync_task_card_from_outline(
            PROJECT_DIR,
            chapter_num,
            read_file(f"01_大纲/章纲/第{ch}章.md"),
            preserve_confirmation=False,
            llm=llm,
            context=build_axis_context(PROJECT_DIR),
        )
        messages.append(f"任务卡已生成：{card.title}")
    elif action == "confirm_task_card":
        from structured_store import confirm_task_card

        card = confirm_task_card(PROJECT_DIR, chapter_num)
        messages.append(f"任务卡已自动确认：{card.title}")
    elif action == "plan_scenes":
        from llm_router import LLMRouter
        from prompt_assembly import build_axis_context
        from structured_store import sync_scene_plan_from_task_card

        scenes = sync_scene_plan_from_task_card(
            PROJECT_DIR,
            chapter_num,
            llm=LLMRouter(project_dir=PROJECT_DIR),
            context=build_axis_context(PROJECT_DIR),
        )
        messages.append(f"场景计划已生成：{len(scenes)} 个场景")
    elif action == "draft_scene":
        from novel_pipeline import run_scene_draft

        scene_number = int(rec.get("scene_number", 1))
        run_scene_draft(chapter_num, scene_number, mock=mock)
        messages.append(f"场景 {scene_number:03d} 候选稿已生成")
    elif action == "assemble_scenes":
        from novel_pipeline import run_assemble_scenes

        run_assemble_scenes(chapter_num)
        messages.append("场景已合并为章节草稿")
    elif action == "full_pipeline":
        from novel_pipeline import run_full

        run_full(chapter_num, mock=mock)
        messages.append("章节草稿与基础审查已完成")
    elif action == "audit":
        from novel_pipeline import run_audit_only

        run_audit_only(chapter_num, mock=mock)
        messages.append("逻辑审计已完成")
    elif action == "ai_check":
        source, text = latest_chapter_text(ch)
        if not text:
            raise RuntimeError("找不到可检查稿件")
        from llm_router import LLMRouter

        result = LLMRouter(project_dir=PROJECT_DIR).check_ai_flavor_local(text)
        write_file(f"04_审核日志/第{ch}章_AI味检查.md", result)
        messages.append(f"AI 味检查已完成：{source}")
    elif action == "reader_mirror":
        source, text = latest_chapter_text(ch)
        if not text:
            raise RuntimeError("找不到可检查稿件")
        from llm_router import LLMRouter

        result = LLMRouter(project_dir=PROJECT_DIR).reader_mirror(text, read_file("03_滚动记忆/最近摘要.md"))
        write_file(f"04_审核日志/第{ch}章_读者镜像.md", result)
        messages.append(f"读者镜像已完成：{source}")
    elif action == "deep_check":
        source, text = latest_chapter_text(ch)
        if not text:
            raise RuntimeError("找不到可检查稿件")
        from llm_router import LLMRouter

        result = LLMRouter(project_dir=PROJECT_DIR).deep_check(text, read_file("03_滚动记忆/最近摘要.md"))
        write_file(f"04_审核日志/第{ch}章_深度检查.md", result)
        messages.append(f"深度检查已完成：{source}")
    elif action == "quality_diag":
        source, text = latest_chapter_text(ch)
        if not text:
            raise RuntimeError("找不到可诊断稿件")
        from quality_diagnostics import write_quality_diagnostics

        _, _, report = write_quality_diagnostics(PROJECT_DIR, chapter_num, text, source)
        messages.append(f"质量诊断已完成：{report['grade']}")
    elif action == "feedback_revise":
        from novel_pipeline import run_revise_from_feedback

        run_revise_from_feedback(chapter_num, mock=mock)
        messages.append("诊断驱动修订稿已生成")
    elif action == "save_final":
        src = read_file(f"02_正文/第{ch}章_修订稿.md").strip() and f"02_正文/第{ch}章_修订稿.md" or f"02_正文/第{ch}章_草稿.md"
        write_file(f"02_正文/第{ch}章_定稿.md", read_file(src))
        messages.append("已保存为定稿")
    elif action == "finalize_memory":
        from novel_pipeline import run_finalize

        run_finalize(chapter_num, yes=True, mock=mock)
        messages.append("长期记忆与 RAG 索引已更新")
    return messages


def _autopilot_stop_message(action: str, rec: dict) -> str:
    if action == "edit_outline":
        return "章纲还有占位符或缺失内容，AI 暂停接手。"
    if action == "complete":
        return "本章闭环已完成。"
    return rec.get("detail", "已暂停。")


def _render_command_panel(
    chapter_num: int,
    ch: str,
    state: dict,
    mock_mode: bool,
    llm_lock: bool,
) -> None:
    with st.expander("手工控制台（备用）", expanded=True):
        _render_chapter_mini_status(chapter_num)

        with st.expander("快捷操作", expanded=False):
            _render_main_actions(chapter_num, ch, state, mock_mode, llm_lock)

        with st.expander("技巧焦点", expanded=False):
            _render_technique_selector(chapter_num)

        with st.expander("章节管理", expanded=False):
            _render_delete_chapter_controls(chapter_num, key_prefix="writing_v5")
            for key, label in shortcut_cheatsheet():
                st.caption(f"{key} ｜ {label}")


def _render_diagnostics_drawer(chapter_num: int, ch: str, mock_mode: bool) -> None:
    """V5.0-rc1 诊断抽屉：标签页结构，文学批评为默认标签页。"""
    memo = _load_memo(ch)
    drama = _load_drama_diag(ch)
    quality = _load_quality_diag(ch)
    literary = _load_literary_view(ch)
    court = _load_style_court(ch)

    with st.expander("诊断抽屉", expanded=True):
        tab_lit, tab_eng, tab_style, tab_memo = st.tabs([
            "文学批评", "工程诊断", "风格法庭", "备忘录",
        ])

        with tab_lit:
            _render_literary_panel(literary)

        with tab_eng:
            _render_engineering_panel(chapter_num, ch, drama, quality, mock_mode)

        with tab_style:
            if court:
                _render_style_court(chapter_num, court)
            else:
                st.caption("暂无风格法庭裁决 — 运行完整流水线后生成")

        with tab_memo:
            if memo:
                _render_memo_view(chapter_num, ch, memo, mock_mode)
            else:
                st.caption("暂无编辑备忘录 — 运行完整流水线后自动生成")


def _render_engineering_panel(
    chapter_num: int,
    ch: str,
    drama: dict | None,
    quality: dict | None,
    mock_mode: bool,
) -> None:
    """V5.0-rc1 工程诊断标签页：戏剧雷达 + 质量指标 + 子报告 + 样本池。"""

    # ── 戏剧诊断雷达 ──
    with st.expander("戏剧诊断雷达", expanded=False):
        if drama:
            _render_drama_radar_metrics(drama)
        else:
            st.caption("暂无戏剧诊断")

    # ── 质量诊断指标 ──
    if quality:
        with st.expander("质量诊断指标", expanded=False):
            metrics = quality.get("metrics", {})
            q1, q2, q3 = st.columns(3)
            q1.metric("章首抓力", int(metrics.get("opening_hook_score", 0)))
            q2.metric("章末余味", int(metrics.get("ending_hook_score", 0)))
            q3.metric("追读张力", int(metrics.get("page_turner_score", 0)))
            q4, q5 = st.columns(2)
            q4.metric("文气质地", int(metrics.get("prose_texture_score", 0)))
            q5.metric("读者抓力", int(metrics.get("reader_grip_score", 0)))

    # ── 诊断子报告 ──
    with st.expander("诊断子报告", expanded=False):
        if drama:
            _render_drama_revision_targets(chapter_num, ch, drama, mock_mode)
        if quality:
            with st.expander("质量诊断详情", expanded=False):
                _render_quality_detail(quality)
        _render_sub_reports(ch)

    # ── 文风样本池 ──
    with st.expander("文风样本池", expanded=False):
        _render_sample_pool_management()


def _toggle_state(key: str) -> None:
    st.session_state[key] = not bool(st.session_state.get(key, False))


def _chapter_title(chapter_num: int | None, selected: str) -> str:
    if not chapter_num:
        return selected
    ch = ch_str(chapter_num)
    card_path = PROJECT_DIR / "01_大纲" / "章纲" / f"第{ch}章_task_card.json"
    if card_path.exists():
        try:
            title = json.loads(card_path.read_text(encoding="utf-8")).get("title", "")
            if title:
                return f"第 {ch} 章｜{title}"
        except Exception:
            pass
    outline = read_file(f"01_大纲/章纲/第{ch}章.md")
    for line in outline.splitlines():
        clean = line.strip(" #\t")
        if clean:
            return clean[:40]
    return selected


def _inject_writing_surface_css() -> None:
    st.markdown(
        """
        <style>
        .v5-writing-toolbar {
            position: sticky;
            top: 0;
            z-index: 20;
            padding: 6px 0 10px;
            background: var(--novel-bg);
            border-bottom: 1px solid var(--novel-border);
        }
        .v5-toolbar-title {
            min-height: 38px;
            display: flex;
            align-items: center;
            font-size: 18px;
            font-weight: 650;
            color: var(--novel-text);
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .v5-paper-wrap {
            max-width: 100%;
            margin: 10px 0 0;
        }
        .v5-paper-status {
            display: flex;
            justify-content: space-between;
            gap: 14px;
            color: var(--novel-muted);
            font-size: 12px;
            padding: 8px 2px 0;
        }
        .v5-margin-note {
            border-left: 2px solid var(--novel-accent-2);
            padding: 6px 0 6px 10px;
            margin-bottom: 10px;
            color: var(--novel-text);
            font-size: 13px;
        }
        .v5-margin-note small {
            color: var(--novel-muted);
        }
        .v5-focus-pill {
            position: fixed;
            right: 18px;
            bottom: 18px;
            z-index: 50;
            background: var(--novel-text);
            color: var(--novel-panel);
            padding: 6px 10px;
            border-radius: 999px;
            font-size: 12px;
        }
        div[data-testid="stTextArea"] textarea {
            max-width: 100%;
            margin-left: auto;
            margin-right: auto;
            display: block;
            font-family: "Noto Serif SC", "Source Han Serif SC", "Songti SC", serif;
            font-size: 18px;
            line-height: 1.85;
            letter-spacing: 0;
            background: var(--novel-panel) !important;
            border: 1px solid var(--novel-border) !important;
            border-radius: 8px !important;
            padding: 24px 28px !important;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )
# ─────────────────────────────────────────────────────────────────────────────
# 左栏辅助
# ─────────────────────────────────────────────────────────────────────────────

def _default_chapter_index(outlines: list[str]) -> int:
    """返回首个非定稿章节的索引，找不到时返回 0。"""
    for i, name in enumerate(outlines):
        num = parse_chapter_num(name)
        if num and chapter_status(num) != "已定稿":
            return i
    return 0


def _render_chapter_mini_status(chapter_num: int) -> None:
    """在左栏显示简化状态卡（字数、状态标签）。"""
    ch = ch_str(chapter_num)
    _, text = latest_chapter_text(ch)
    wc = word_count(text) if text else 0
    status_label = chapter_status(chapter_num)
    st.markdown(
        f'<div class="novel-card" style="padding:8px 10px;">'
        f'<span style="font-size:13px;">{status_label}</span><br>'
        f'<span class="novel-muted">{wc:,} 字</span></div>',
        unsafe_allow_html=True,
    )


def _render_technique_selector(chapter_num: int) -> None:
    """左栏技巧焦点选择器，保存到任务卡 technique_focus 字段。"""
    tech_path = PROJECT_DIR / "01_大纲" / "章纲" / f"第{chapter_num:03d}章_task_card.json"
    current: list[str] = []
    if tech_path.exists():
        try:
            data = json.loads(tech_path.read_text(encoding="utf-8"))
            current = data.get("technique_focus", [])
        except Exception:
            pass

    all_techniques = [
        "短句冲击", "感官锚点", "潜台词", "身体反应替代副词",
        "身体化情感", "连续动作链", "留白", "信息折叠", "环境拟人",
    ]
    default_techniques = [t for t in current if t in all_techniques] if current else None
    selected = st.multiselect(
        "技巧焦点",
        all_techniques,
        default=default_techniques,
        key="_writing_technique_focus",
        help="选中技巧将作为硬指令注入 prose 生成 prompt",
    )

    if set(selected) != set(current) and st.button("保存技巧", key="_save_techniques"):
        if tech_path.exists():
            try:
                data = json.loads(tech_path.read_text(encoding="utf-8"))
                data["technique_focus"] = selected
                tech_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                st.toast(f"已保存 {len(selected)} 个技巧焦点")
            except Exception:
                st.warning("保存技巧失败")


# ─────────────────────────────────────────────────────────────────────────────
# 中栏：主操作按钮
# ─────────────────────────────────────────────────────────────────────────────

def _detect_primary_action(state: dict, drama: dict | None) -> str:
    """根据章节状态和戏剧诊断分数，返回当前推荐主操作 key。"""
    has_any = state["draft"] or state["revised"] or state["final"]
    if not has_any:
        return "pipeline"
    if drama and not drama.get("is_mock"):
        score = drama.get("overall_drama_score", 0)
        if score >= 75:
            return "finalize"
        return "revise"
    return "pipeline"  # 有草稿但无真实诊断 → 建议跑完整流水线补诊断


def _render_main_actions(
    chapter_num: int,
    ch: str,
    state: dict,
    mock_mode: bool,
    llm_lock: bool,
) -> None:
    """主操作 3 按钮，始终可见，根据章节状态高亮推荐操作。"""
    drama = _load_drama_diag(ch)
    primary = _detect_primary_action(state, drama)

    has_any = state["draft"] or state["revised"] or state["final"]
    can_pipeline = (
        bool(state["outline"])
        and not llm_lock
        and (state["task_card_confirmed"] or st.session_state.get("_writing_ignore_taskcard", False))
        and (not state["placeholders"] or st.session_state.get("_writing_ignore_ph", False))
    )

    c1, c2, c3 = st.columns(3)

    do_pipeline = c1.button(
        "流水线",
        type="primary" if primary == "pipeline" else "secondary",
        use_container_width=True,
        disabled=not can_pipeline,
        help="生成草稿 → 审计 → 质量诊断 → 戏剧诊断 → 修订",
        key=f"writing3_pipeline_{ch}",
    )
    do_revise = c2.button(
        "改稿",
        type="primary" if primary == "revise" else "secondary",
        use_container_width=True,
        disabled=not has_any or llm_lock,
        help="按审计 + 质量诊断 + 戏剧诊断合成改稿指令",
        key=f"writing3_revise_{ch}",
    )
    confirm_finalize = st.checkbox("确认定稿（会覆盖已有定稿）", key=f"writing3_confirm_finalize_{ch}")
    do_finalize = c3.button(
        "定稿",
        type="primary" if primary == "finalize" else "secondary",
        use_container_width=True,
        disabled=not has_any or llm_lock or not confirm_finalize,
        help="保存为定稿文件（长期记忆更新需在折叠区确认）",
        key=f"writing3_finalize_{ch}",
    )

    st.caption(f"{'Mock 离线' if mock_mode else prose_model_label(mock_mode)}")

    # 执行按钮
    if do_pipeline:
        _run_pipeline(
            chapter_num,
            generate=True, audit=True, ai_check=True,
            reader_mirror=True, deep_check=True, quality=True,
            mock=mock_mode,
        )
        st.rerun()

    if do_revise:
        _run_feedback_revision(chapter_num, mock=mock_mode)
        st.rerun()

    if do_finalize:
        has_revised = bool(read_file(f"02_正文/第{ch}章_修订稿.md").strip())
        has_draft = bool(read_file(f"02_正文/第{ch}章_草稿.md").strip())
        src = f"02_正文/第{ch}章_修订稿.md" if has_revised else f"02_正文/第{ch}章_草稿.md"
        if has_revised or has_draft:
            write_file(f"02_正文/第{ch}章_定稿.md", read_file(src))
            st.success("已保存为定稿草案，长期记忆尚未更新（在高级操作中确认）。")
            st.rerun()

    # 高级操作折叠区（低频）
    with st.expander("高级操作", expanded=False):
        _render_advanced_actions(chapter_num, ch, state, mock_mode, llm_lock)


def _render_advanced_actions(
    chapter_num: int,
    ch: str,
    state: dict,
    mock_mode: bool,
    llm_lock: bool,
) -> None:
    """高级/低频操作：智能推荐、逐步审计、定稿+更新记忆、场景、AI辅助、版本。"""
    has_any = state["draft"] or state["revised"] or state["final"]

    st.subheader("智能推荐")
    _render_smart_action_panel(
        chapter_num, mock=mock_mode,
        allow_blocked=st.session_state.get("_writing_ignore_ph", False),
        key_prefix="writing3adv",
    )

    st.divider()
    st.subheader("逐步操作")
    col_a, col_b, col_c = st.columns(3)
    any_dis = not has_any or llm_lock
    col_a.button("逻辑审计", use_container_width=True, disabled=any_dis, key=f"w3adv_audit_{ch}",
                 on_click=lambda m=mock_mode: _run_pipeline(chapter_num, False, True, False, False, False, False, m))
    col_a.button("AI 味检查", use_container_width=True, disabled=any_dis, key=f"w3adv_ai_{ch}",
                 on_click=lambda m=mock_mode: _run_pipeline(chapter_num, False, False, True, False, False, False, m))
    col_b.button("读者镜像", use_container_width=True, disabled=any_dis, key=f"w3adv_mirror_{ch}",
                 on_click=lambda m=mock_mode: _run_pipeline(chapter_num, False, False, False, True, False, False, m))
    col_b.button("深度检查", use_container_width=True, disabled=any_dis, key=f"w3adv_deep_{ch}",
                 on_click=lambda m=mock_mode: _run_pipeline(chapter_num, False, False, False, False, True, False, m))
    col_c.button("质量诊断", use_container_width=True, disabled=any_dis, key=f"w3adv_quality_{ch}",
                 on_click=lambda m=mock_mode: _run_pipeline(chapter_num, False, False, False, False, False, True, m))

    st.divider()
    st.subheader("定稿 + 长期记忆")
    with st.form(key=f"w3adv_finalize_mem_form_{ch}", border=False):
        confirm_mem = st.checkbox("确认更新长期记忆", key=f"w3adv_confirm_mem_{ch}")
        submitted = st.form_submit_button(
            "定稿并更新记忆",
            disabled=not has_any or llm_lock,
        )
        if submitted:
            if not confirm_mem:
                st.warning("请先勾选「确认更新长期记忆」再提交")
            else:
                _run_finalize(chapter_num, mock=mock_mode)
                st.rerun()

    st.divider()
    st.subheader("场景工作台")
    _scene_workspace(chapter_num, mock_mode)

    st.divider()
    st.subheader("AI 辅助写作")
    _render_writing_assist(chapter_num, mock_mode, key_prefix="command_panel_ai")

    with st.expander("历史草案兼容入口", expanded=False):
        _render_assist_candidate_adoption(chapter_num, key_prefix="writing3adv", title="历史草案采纳", show_empty=True)


# ─────────────────────────────────────────────────────────────────────────────
# 中栏：正文预览
# ─────────────────────────────────────────────────────────────────────────────

def _render_draft_view(
    chapter_num: int,
    ch: str,
    state: dict,
    mock_mode: bool,
    llm_lock: bool,
) -> None:
    """单栏稿纸 + 低频章纲/对比入口。"""
    tab_text, tab_outline, tab_diff = st.tabs(["稿纸", "章纲", "修订对比"])

    with tab_text:
        source_rel, text = latest_chapter_text(ch)
        if text:
            st.markdown('<div class="v5-paper-wrap">', unsafe_allow_html=True)
            _render_inline_revision_preview(ch, source_rel)

            quality = _load_quality_diag(ch)
            notes = build_margin_notes(text, quality, limit=5)
            if notes and not st.session_state.get("_writing_focus_mode", False):
                paper_col, note_col = st.columns([5.5, 1.35], gap="medium")
            else:
                paper_col, note_col = st.container(), None

            with paper_col:
                edited = st.text_area(
                    "正文编辑",
                    text,
                    height=680 if st.session_state.get("_writing_focus_mode", False) else 620,
                    key=f"draft_editor_{ch}",
                    label_visibility="collapsed",
                )
                _render_paper_status(chapter_num, ch, source_rel, edited, text)
                save_requested = bool(st.session_state.pop("_writing_save_requested", False))
                col_save, col_focus, _ = st.columns([1, 1, 4])
                with col_save:
                    if st.button("保存", key=f"save_draft_{ch}",
                                 use_container_width=True, disabled=llm_lock):
                        _save_paper_edit(ch, source_rel, edited)
                with col_focus:
                    if st.button("专注", key=f"focus_draft_{ch}", use_container_width=True):
                        _toggle_state("_writing_focus_mode")
                        st.rerun()
                if save_requested and edited != text and not llm_lock:
                    _save_paper_edit(ch, source_rel, edited)

            if note_col:
                with note_col:
                    _render_margin_note_rail(chapter_num, notes)

            st.markdown("</div>", unsafe_allow_html=True)

            with st.expander("行级 AI 改写", expanded=bool(st.session_state.get("_writing_ai_panel", False))):
                _render_line_assist_controls(chapter_num, ch, edited, mock_mode, llm_lock)
        else:
            st.info("尚未生成。点击上方「AI 自动推进当前章」开始。")
            if st.button(
                "AI 自动写出本章",
                key=f"autopilot_empty_{ch}",
                type="primary",
                use_container_width=True,
                disabled=llm_lock,
            ):
                _run_chapter_autopilot(chapter_num, mock_mode)
                st.rerun()

    with tab_outline:
        outline_text = read_file(f"01_大纲/章纲/第{ch}章.md")
        if outline_text:
            st.markdown(outline_text)
        else:
            st.info("章纲为空。可以直接在这里让 AI 补全，不需要切到大纲页。")
            if st.button(
                "AI 补全本章章纲",
                type="primary",
                use_container_width=True,
                disabled=llm_lock,
                key=f"outline_tab_autofill_{ch}",
            ):
                _run_integrated_chapter_outline_job(chapter_num, mock_mode)
                st.rerun()

    with tab_diff:
        _render_revision_diff(ch)


def _render_paper_status(chapter_num: int, ch: str, source_rel: str, edited: str, saved_text: str) -> None:
    wc = word_count(edited)
    target = _target_words(chapter_num)
    target_text = f"目标 {target}" if target else "未设目标"
    dirty = edited != saved_text
    saved_at = st.session_state.get(f"_writing_last_saved_{ch}", "尚未保存")
    status = "有未保存修改" if dirty else f"已保存 {saved_at}"
    st.markdown(
        f"<div class='v5-paper-status'>"
        f"<span>{wc:,} 字 ｜ {target_text}</span>"
        f"<span>{source_rel.split('/')[-1]} ｜ {status}</span>"
        f"</div>",
        unsafe_allow_html=True,
    )


def _target_words(chapter_num: int) -> str:
    ch = ch_str(chapter_num)
    path = PROJECT_DIR / "01_大纲" / "章纲" / f"第{ch}章_task_card.json"
    if not path.exists():
        return ""
    try:
        value = json.loads(path.read_text(encoding="utf-8")).get("target_words", "")
    except Exception:
        return ""
    return str(value or "").strip()


def _save_paper_edit(ch: str, source_rel: str, edited: str) -> None:
    write_file(source_rel, edited, preserve_existing=True)
    st.session_state[f"_writing_last_saved_{ch}"] = datetime.now().strftime("%H:%M")
    st.toast(f"已保存 → {source_rel.split('/')[-1]}")
    st.rerun()


def _render_margin_note_rail(chapter_num: int, notes: list[MarginNote]) -> None:
    st.caption("页边批注")
    for idx, note in enumerate(notes):
        key = f"{chapter_num}_{idx}_{abs(hash(note.note_id))}"
        with st.container():
            st.markdown(
                f"<div class='v5-margin-note'>"
                f"<small>段落 {note.paragraph_index} · {note.level}</small><br>"
                f"<strong>{note.title}</strong><br>"
                f"<small>{note.quote}</small>"
                f"</div>",
                unsafe_allow_html=True,
            )
            col_see, col_skip = st.columns(2)
            if col_see.button("看看", key=f"note_see_{key}", use_container_width=True):
                st.session_state["_writing_diag_drawer"] = True
                st.session_state["_writing_focus_note"] = note.note_id
                st.toast(note.detail or note.suggestion or note.title)
                st.rerun()
            # V5.0-rc1: "不用" 改为 popover 选择保护/反驳
            skip_popover = col_skip.popover("不用", key=f"note_skip_pop_{key}", use_container_width=True)
            with skip_popover:
                st.caption("保护 = 保留文本不修 / 反驳 = 诊断有误")
                reason = st.text_area(
                    "理由", key=f"note_skip_reason_{key}",
                    placeholder="可选，为空时默认保护",
                    label_visibility="collapsed", height=60,
                )
                col_p, col_r = st.columns(2)
                if col_p.button("保护", key=f"note_protect_{key}", use_container_width=True):
                    from quality_diagnostics import write_writer_override
                    write_writer_override(
                        PROJECT_DIR, chapter_num,
                        rejected_advice=note.title,
                        writer_reason=reason.strip() or "作家在页边批注中选择不用，保留当前写法。",
                        diagnostic_source=note.diagnostic_source,
                        finding_key=note.finding_key,
                        action="protect",
                    )
                    st.toast("已保护并写入作家豁免。")
                    st.rerun()
                if col_r.button("反驳", key=f"note_rebut_{key}", use_container_width=True):
                    from quality_diagnostics import write_writer_override
                    write_writer_override(
                        PROJECT_DIR, chapter_num,
                        rejected_advice=note.title,
                        writer_reason=reason.strip() or "作家反驳此诊断。",
                        diagnostic_source=note.diagnostic_source,
                        finding_key=note.finding_key,
                        action="rebut",
                    )
                    st.toast("已反驳此诊断。")
                    st.rerun()


def _render_line_assist_controls(
    chapter_num: int,
    ch: str,
    edited: str,
    mock_mode: bool,
    llm_lock: bool,
) -> None:
    ca1, ca2, ca3 = st.columns([1, 1, 2])
    total_lines = max(1, edited.count("\n") + 1)
    with ca1:
        line_start = st.number_input(
            "起行", min_value=1, max_value=total_lines, value=1,
            key=f"assist_ls_{ch}",
        )
    with ca2:
        line_end = st.number_input(
            "止行", min_value=1, max_value=total_lines, value=total_lines,
            key=f"assist_le_{ch}",
        )
    with ca3:
        action = st.selectbox(
            "润色动作",
            ["show-dont-tell", "tighten-dialogue", "add-sensory",
             "body-emotion", "strengthen-hook", "vary-sentence"],
            format_func={
                "show-dont-tell": "描写代替叙述",
                "tighten-dialogue": "对白精炼",
                "add-sensory": "感官细节",
                "body-emotion": "身体化情绪",
                "strengthen-hook": "强化钩子",
                "vary-sentence": "句式多样化",
            }.__getitem__,
            key=f"assist_action_{ch}",
            label_visibility="collapsed",
        )
    if st.button("单段改写", key=f"inline_assist_{ch}",
                 disabled=llm_lock, use_container_width=True):
        _run_inline_assist(
            chapter_num, ch, edited, line_start, line_end, action, mock_mode,
        )


def _inline_revision_key(ch: str) -> str:
    return f"_inline_revision_preview_{ch}"


def _store_inline_revision_preview(
    ch: str,
    source_rel: str,
    original: str,
    revised: str,
    reason: str,
) -> None:
    st.session_state[_inline_revision_key(ch)] = {
        "source_rel": source_rel,
        "original": original,
        "revised": revised,
        "reason": reason,
        "decisions": {},
    }


def _build_inline_revision_blocks(original: str, revised: str) -> list[dict]:
    original_lines = original.splitlines(keepends=True)
    revised_lines = revised.splitlines(keepends=True)
    matcher = difflib.SequenceMatcher(a=original_lines, b=revised_lines)
    blocks: list[dict] = []
    for index, (tag, i1, i2, j1, j2) in enumerate(matcher.get_opcodes()):
        blocks.append({
            "id": str(index),
            "tag": tag,
            "old": "".join(original_lines[i1:i2]),
            "new": "".join(revised_lines[j1:j2]),
            "old_range": (i1 + 1, i2),
            "new_range": (j1 + 1, j2),
        })
    return blocks


def _compose_inline_revision(blocks: list[dict], decisions: dict[str, str]) -> str:
    parts: list[str] = []
    for block in blocks:
        if block["tag"] == "equal":
            parts.append(block["old"])
            continue
        choice = decisions.get(block["id"], "pending")
        parts.append(block["new"] if choice == "accept" else block["old"])
    return "".join(parts)


def _block_title(block: dict) -> str:
    labels = {
        "replace": "替换",
        "delete": "删除",
        "insert": "新增",
        "equal": "保留",
    }
    old_start, old_end = block["old_range"]
    if block["tag"] == "insert":
        return f"{labels.get(block['tag'], block['tag'])} · 原稿第 {old_start} 行后"
    return f"{labels.get(block['tag'], block['tag'])} · 原稿第 {old_start}-{old_end} 行"


def _render_inline_revision_preview(ch: str, source_rel: str) -> None:
    preview = st.session_state.get(_inline_revision_key(ch))
    if not preview:
        return
    if preview.get("source_rel") != source_rel:
        st.session_state.pop(_inline_revision_key(ch), None)
        return

    original = preview.get("original", "")
    revised = preview.get("revised", "")
    blocks = preview.get("blocks") or _build_inline_revision_blocks(original, revised)
    preview["blocks"] = blocks
    decisions = preview.setdefault("decisions", {})
    changed_blocks = [block for block in blocks if block["tag"] != "equal"]
    accepted = sum(1 for block in changed_blocks if decisions.get(block["id"]) == "accept")
    rejected = sum(1 for block in changed_blocks if decisions.get(block["id"]) == "reject")
    pending = len(changed_blocks) - accepted - rejected
    current_on_disk = read_file(source_rel)
    stale = bool(current_on_disk and current_on_disk != original)

    with st.container(border=True):
        st.markdown("**待采纳改法**")
        st.caption(preview.get("reason", ""))
        st.caption(f"差异块：{len(changed_blocks)} · 已采用 {accepted} · 已保留原文 {rejected} · 待裁决 {pending}")
        if stale:
            st.warning("源文件已在生成建议后发生变化。建议先保存或重新生成 diff，避免覆盖新改动。")
        if not changed_blocks:
            st.info("建议稿与当前稿没有差异。")

        c_all, c_keep, c_write, c_discard = st.columns([1, 1, 1.2, 1])
        if c_all.button("全部采用", key=f"accept_all_inline_revision_{ch}"):
            for block in changed_blocks:
                decisions[block["id"]] = "accept"
            st.rerun()
        if c_keep.button("全部保留", key=f"reject_all_inline_revision_{ch}"):
            for block in changed_blocks:
                decisions[block["id"]] = "reject"
            st.rerun()
        if c_write.button("写入已裁决版本", type="primary", key=f"write_inline_revision_{ch}",
                          disabled=stale or pending > 0 or not changed_blocks):
            write_file(source_rel, _compose_inline_revision(blocks, decisions), preserve_existing=True)
            st.session_state.pop(_inline_revision_key(ch), None)
            st.toast("已采用改法并写入正文")
            st.rerun()
        if c_discard.button("丢弃", key=f"discard_inline_revision_{ch}"):
            st.session_state.pop(_inline_revision_key(ch), None)
            st.toast("已丢弃本次改法")
            st.rerun()

        for block in changed_blocks:
            choice = decisions.get(block["id"], "pending")
            with st.container(border=True):
                st.markdown(f"**{_block_title(block)}**")
                c_old, c_new = st.columns(2)
                c_old.caption("当前稿")
                c_old.code(block["old"] or "（无）", language="markdown")
                c_new.caption("建议稿")
                c_new.code(block["new"] or "（删除）", language="markdown")
                b_accept, b_reject, b_state = st.columns([1, 1, 2])
                if b_accept.button("采用此块", key=f"accept_inline_block_{ch}_{block['id']}",
                                   type="primary" if choice == "accept" else "secondary"):
                    decisions[block["id"]] = "accept"
                    st.rerun()
                if b_reject.button("保留原文", key=f"reject_inline_block_{ch}_{block['id']}",
                                   type="primary" if choice == "reject" else "secondary"):
                    decisions[block["id"]] = "reject"
                    st.rerun()
                b_state.caption({"accept": "当前选择：采用建议", "reject": "当前选择：保留原文"}.get(
                    choice, "当前选择：待裁决"
                ))


def _run_inline_assist(
    chapter_num: int, ch: str, full_text: str,
    line_start: int, line_end: int, action: str, mock: bool,
) -> None:
    """选中行范围 → 按动作改写 → 生成可一键采用的 inline diff。"""
    lines = full_text.splitlines()
    if line_start < 1:
        line_start = 1
    if line_end > len(lines):
        line_end = len(lines)
    if line_start > line_end:
        line_start, line_end = line_end, line_start
    target = "\n".join(lines[line_start - 1:line_end])

    action_prompts = {
        "show-dont-tell": (
            "将以下段落中的抽象叙述改为具体可感知的动作、表情和场景细节。"
            "不说'他很生气'，而是写出他捏紧了拳头、呼吸急促、声音发抖。"
            "不用'优雅'这类形容词，而是写出她指节微曲、酒液未洒、裙摆随步态轻转。"
        ),
        "tighten-dialogue": (
            "精炼以下段落中的对白：删除语义重复的句子，把长解释改为短交锋，"
            "把'明确回答'改成暗示、反问或不回答，让每句话都携带弦外之音。"
        ),
        "add-sensory": (
            "为以下段落注入三种以上感官细节（视觉之外必须包含听觉/触觉/嗅觉/味觉）。"
            "给一个静态场景加上温度、气流、远处声响、金属味道或织物触感。"
        ),
        "body-emotion": (
            "将以下段落中的情绪形容词替换为身体反应：不写'他感到紧张'，"
            "而写'他拇指一直在掐食指关节，掐出了白印'。"
            "每种情绪至少匹配一个内脏或运动神经反应。"
        ),
        "strengthen-hook": (
            "重写以下段落的结尾句，使其成为追读钩子：一个未揭晓的秘密、"
            "一个即将到来的危机、一句反转的信息、或者一个无法拒绝的抉择。"
            "钩子必须直接关联当前场景的核心冲突。"
        ),
        "vary-sentence": (
            "调整以下段落的句式节奏：如果连续 3 句以上结构相同，打散重组。"
            "前一句长则后一句短，前一句直叙则后一句反问或感叹，"
            "保持长短交错、主动被动交替，避免连续套娃从句。"
        ),
    }

    prompt = (
        f"## 段落润色\n\n"
        f"润色动作：{action}\n"
        f"要求：{action_prompts.get(action, '')}\n\n"
        f"## 目标段落\n\n{target}\n\n"
        f"## 约束\n"
        f"1. 只输出改写后的该段落，不输出全文\n"
        f"2. 保留原有的信息量和情节推进\n"
        f"3. 长度与原文差异不超过 ±15%\n"
        f"4. 保留人物名、地名、伏笔标记\n"
        f"5. 不要任何元说明"
    )

    def work(cancel_event):
        candidate_path = run_writing_assist(chapter_num, "段落润色",
                                            user_request=prompt, mock=mock)
        if cancel_event.is_set():
            return None
        if not candidate_path:
            raise RuntimeError("润色未生成候选稿")
        result = extract_adoptable_assist_text(candidate_path.read_text(encoding="utf-8")).strip()
        revised_lines = lines[:]
        revised_lines[line_start - 1:line_end] = result.splitlines()
        source_rel, _ = latest_chapter_text(ch)
        return {
            "ch": ch,
            "source_rel": source_rel,
            "original": full_text,
            "revised": "\n".join(revised_lines),
            "reason": f"单段改写：{action}（第 {line_start}-{line_end} 行）",
        }

    def done(result):
        if not result:
            return
        _store_inline_revision_preview(
            result["ch"],
            result["source_rel"],
            result["original"],
            result["revised"],
            result["reason"],
        )
        st.success("已生成可逐块裁决的 inline diff。")

    _start_llm_background_job(
        f"AI 辅助润色（{action}）",
        work,
        eta_seconds=75,
        on_success=done,
    )


def _render_revision_diff(ch: str) -> None:
    """渲染草稿 vs 修订稿的 unified diff。"""
    draft_text = read_file(f"02_正文/第{ch}章_草稿.md")
    revised_text = read_file(f"02_正文/第{ch}章_修订稿.md")

    if not draft_text or not revised_text:
        st.info("需要同时有草稿和修订稿才能对比")
        return

    draft_lines = draft_text.splitlines(keepends=True)
    revised_lines = revised_text.splitlines(keepends=True)
    diff = list(difflib.unified_diff(
        draft_lines, revised_lines,
        fromfile="草稿", tofile="修订稿",
        lineterm="",
    ))

    if not diff:
        st.success("草稿与修订稿完全一致")
        return

    added = sum(1 for line in diff if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff if line.startswith("-") and not line.startswith("---"))
    st.caption(f"变更：+{added} 行新增 / -{removed} 行删除")

    st.code("".join(diff), language="diff", line_numbers=True)


# ─────────────────────────────────────────────────────────────────────────────
# 右栏：戏剧诊断面板
# ─────────────────────────────────────────────────────────────────────────────

def _load_drama_diag(ch: str) -> dict | None:
    """读取戏剧诊断 JSON，读取失败返回 None。"""
    p = PROJECT_DIR / "04_审核日志" / f"第{ch}章_戏剧诊断.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_quality_diag(ch: str) -> dict | None:
    """读取质量诊断 JSON，读取失败返回 None。"""
    p = PROJECT_DIR / "04_审核日志" / f"第{ch}章_质量诊断.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_literary_view(ch: str) -> dict | None:
    """读取文学批评 JSON。"""
    p = PROJECT_DIR / "04_审核日志" / f"第{ch}章_文学批评.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_style_court(ch: str) -> dict | None:
    """读取风格法庭 JSON。"""
    p = PROJECT_DIR / "04_审核日志" / f"第{ch}章_风格法庭.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _load_memo(ch: str) -> dict | None:
    """读取编辑备忘录 JSON。"""
    p = PROJECT_DIR / "04_审核日志" / f"第{ch}章_编辑备忘录.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _render_literary_panel(literary: dict | None) -> None:
    """V5.0-rc1 文学批评独立面板 — 展示 LiteraryView 全部字段。"""
    if not literary:
        st.caption("暂无文学批评 — 运行完整流水线或 `--literary-critic` 后生成")
        return

    if literary.get("is_mock"):
        st.caption("[Mock] 未调用真实文学批评模型，仅供离线验收。")
    st.caption(
        "不可量化保护：" + ("是 — 本章文学价值无法被工程指标捕获" if literary.get("cannot_be_quantified") else "否")
    )

    # ── 可记忆瞬间 ──
    moments = literary.get("memorable_moments", [])
    if moments:
        st.markdown("**可被记住的瞬间**")
        for item in moments[:5]:
            if not isinstance(item, dict):
                continue
            quote = item.get("quote", "")
            why = item.get("why_memorable", "")
            fragility = item.get("fragility", "")
            with st.container(border=True):
                st.markdown(f"*「{quote}」*")
                if why:
                    st.caption(f"为何可记：{why}")
                if fragility:
                    st.caption(f"脆弱处：{fragility}")

    # ── 未说之语 ──
    unsaid = literary.get("unsaid_tension", [])
    if unsaid:
        st.markdown("**未说之语**")
        for value in unsaid[:5]:
            st.markdown(f"- {value}")

    # ── 道德灰度（V5.0-rc1 新增） ──
    moral = literary.get("moral_ambiguity", [])
    if moral:
        st.markdown("**道德灰度**")
        for value in moral[:5]:
            st.markdown(f"- {value}")

    # ── 自我欺骗信号（V5.0-rc1 新增） ──
    self_dec = literary.get("self_deception_signals", [])
    if self_dec:
        st.markdown("**自我欺骗信号**")
        for value in self_dec[:5]:
            st.markdown(f"- {value}")

    # ── 读者残响 ──
    residue = literary.get("reader_residue", [])
    if residue:
        st.markdown("**读者残响**")
        for value in residue[:5]:
            st.markdown(f"- {value}")

    # ── 文学风险 ──
    risks = literary.get("literary_risks", [])
    if risks:
        st.markdown("**文学风险**")
        for value in risks[:5]:
            st.markdown(
                f"<small style='border-left:3px solid var(--status-bad);padding-left:8px;color:var(--novel-muted);'>{value}</small>",
                unsafe_allow_html=True,
            )


# 向后兼容别名
_render_literary_view = _render_literary_panel


def _render_style_court(chapter_num: int, court: dict) -> None:
    """渲染风格法庭 confirmed / contested（V5.0-rc1 接入作家裁决）。"""
    st.caption(
        f"章节模式：{court.get('chapter_mode') or '未指定'}  |  "
        f"风格档案：{court.get('style_profile') or '未指定'}"
    )
    contested = court.get("contested_issues", [])
    confirmed = court.get("confirmed_issues", [])
    priorities = court.get("literary_priorities", [])

    if contested:
        st.markdown("**Contested Issues**")
        # V5.0-rc1: contested issues 可被作家裁决
        findings_for_adj = [
            {
                "item": item.get("issue", ""),
                "detail": item.get("reason", ""),
                "diagnostic_source": item.get("source", ""),
                "finding_key": item.get("finding_key", ""),
                "level": "contested",
            }
            for item in contested[:6] if isinstance(item, dict)
        ]
        from webui_infra.components.adjudication import render_adjudication_panel
        render_adjudication_panel(PROJECT_DIR, chapter_num, findings_for_adj, source_label="风格法庭 Contested")
        # 保留原有摘要
        for item in contested[:6]:
            if not isinstance(item, dict):
                continue
            st.markdown(f"- [{item.get('source', '')}] {item.get('issue', '')}")
            if item.get("reason"):
                st.caption(item.get("reason"))

    if confirmed:
        st.markdown("**Confirmed Issues**")
        for item in confirmed[:6]:
            if isinstance(item, dict):
                st.markdown(f"- [{item.get('source', '')}] {item.get('issue', '')}")
    if priorities:
        st.markdown("**Literary Priorities**")
        for item in priorities[:5]:
            st.markdown(f"- {item}")


def _render_memo_view(
    chapter_num: int,
    ch: str,
    memo: dict,
    mock_mode: bool,
) -> None:
    """渲染编辑备忘录主视图：top-3 行动项 + 评分摘要 + 就绪标志。"""
    scores = memo.get("score_summary", {})
    if scores:
        label_map = {"drama": "戏剧", "quality": "质量", "audit": "审计",
                      "ai_flavor": "AI味", "reader": "读者", "deep": "深度"}
        cols = st.columns(len(scores))
        for idx, (key, val) in enumerate(scores.items()):
            cols[idx].metric(label_map.get(key, key), val)

    ready = memo.get("ready_to_finalize", False)
    st.caption(f"定稿就绪：{'是' if ready else '否 - 仍有改进空间'}")

    llm_lock = is_llm_running(st.session_state)
    items = memo.get("top_3_must_fix", [])
    if items:
        st.markdown("**改稿行动项**")
        for i, item in enumerate(items):
            prio = item.get("priority", "")
            prio_color = {
                "P0": "var(--status-bad)",
                "P1": "var(--brand-secondary)",
                "P2": "var(--brand-primary)",
            }.get(prio, "var(--text-muted)")
            with st.container(border=True):
                st.markdown(
                    f"**[{prio}]** <span style='color:{prio_color}'>{item.get('issue', '')}</span>",
                    unsafe_allow_html=True,
                )
                st.caption(
                    f"来源：{item.get('source', '')}  |  "
                    f"位置：{item.get('location', '未指定')}"
                )
                if item.get("action"):
                    st.markdown(f"改法：{item['action']}")
                if item.get("acceptance"):
                    st.caption(f"验收：{item['acceptance']}")
                # V5.0-rc1: 三态裁决按钮
                col_adopt, col_protect, col_rebut = st.columns(3, gap="small")
                if col_adopt.button(
                    "采纳此改法", key=f"adopt_memo_{ch}_{i}",
                    disabled=llm_lock, use_container_width=True,
                ):
                    from quality_diagnostics import write_writer_override
                    write_writer_override(
                        PROJECT_DIR, chapter_num,
                        rejected_advice=str(item.get("issue", "")),
                        writer_reason="作家采纳此备忘录建议，将在改稿中执行。",
                        diagnostic_source="memo",
                        finding_key=f"memo:top3:{i}",
                        action="adopt",
                    )
                    _run_memo_item_revision(chapter_num, item, mock_mode)
                if col_protect.button("保护", key=f"protect_memo_{ch}_{i}", use_container_width=True):
                    from quality_diagnostics import write_writer_override
                    write_writer_override(
                        PROJECT_DIR, chapter_num,
                        rejected_advice=str(item.get("issue", "")),
                        writer_reason="作家选择保护此处，不修改。",
                        diagnostic_source="memo",
                        finding_key=f"memo:top3:{i}",
                        action="protect",
                    )
                    st.toast("已保护此建议，不再进入改稿清单。")
                    st.rerun()
                if col_rebut.button("反驳", key=f"rebut_memo_{ch}_{i}", use_container_width=True):
                    from quality_diagnostics import write_writer_override
                    write_writer_override(
                        PROJECT_DIR, chapter_num,
                        rejected_advice=str(item.get("issue", "")),
                        writer_reason="作家反驳此诊断，判断有误。",
                        diagnostic_source="memo",
                        finding_key=f"memo:top3:{i}",
                        action="rebut",
                    )
                    st.toast("已反驳此诊断。")
                    st.rerun()
    else:
        st.success("本章无必改项")

    contradictions = memo.get("contradictions", [])
    if contradictions:
        st.warning("诊断间矛盾：" + "；".join(contradictions))

    reservations = memo.get("reservations", [])
    if reservations:
        with st.expander("作家已保护的诊断", expanded=False):
            for item in reservations:
                st.markdown(
                    f"- **{item.get('rejected_advice', '')}**：{item.get('writer_reason', '')}"
                )

    if memo.get("overall_assessment"):
        st.info(memo["overall_assessment"])

    if memo.get("is_mock"):
        st.caption("( Mock 备忘录，仅供验收 )")


def _run_memo_item_revision(chapter_num: int, item: dict, mock: bool) -> None:
    """执行单条备忘录建议 → 生成可一键采用的 inline diff。"""
    prompt = (
        f"## 编辑备忘录改稿任务\n\n"
        f"问题：{item.get('issue', '')}\n"
        f"位置：{item.get('location', '未指定')}\n"
        f"改法：{item.get('action', '请根据问题自动判断')}\n"
        f"验收：{item.get('acceptance', '改后自行检查')}\n\n"
        f"## 约束\n"
        f"1. 只改上述位置涉及的段落，不改其他部分\n"
        f"2. 保留所有人物名称、伏笔、场景事实\n"
        f"3. 全文长度变化控制在 ±5%\n"
        f"4. 直接输出完整章节正文"
    )
    def work(cancel_event):
        candidate_path = run_writing_assist(
            chapter_num, "备忘录改稿",
            user_request=prompt, mock=mock,
        )
        if cancel_event.is_set():
            return None
        if not candidate_path:
            raise RuntimeError("改稿未生成候选稿")
        source_rel, original = latest_chapter_text(ch_str(chapter_num))
        revised = extract_adoptable_assist_text(candidate_path.read_text(encoding="utf-8")).strip()
        return {
            "ch": ch_str(chapter_num),
            "source_rel": source_rel,
            "original": original,
            "revised": revised,
            "reason": f"备忘录改稿：{item.get('issue', '')}",
        }

    def done(result):
        if not result:
            return
        _store_inline_revision_preview(
            result["ch"],
            result["source_rel"],
            result["original"],
            result["revised"],
            result["reason"],
        )
        st.success("已生成可逐块裁决的 inline diff。")

    _start_llm_background_job(
        "备忘录改稿",
        work,
        eta_seconds=90,
        on_success=done,
    )


def _render_drama_radar_metrics(drama: dict) -> None:
    """渲染戏剧诊断四轴指标。"""
    d1, d2, d3, d4 = st.columns(4)
    d1.metric("压力", drama.get("pressure_curve_score", "—"))
    d2.metric("弧光", drama.get("character_arc_score", "—"))
    d3.metric("画面", drama.get("cinematic_score", "—"))
    overall = drama.get("overall_drama_score")
    delta = "↑ 好" if overall and overall >= 75 else ("↓ 需改稿" if overall else None)
    d4.metric("综合", overall if overall else "—", delta=delta)
    if drama.get("is_mock"):
        st.caption("( Mock 诊断，仅供验收 )")

    # V3.1 迷你趋势：当前章综合分 vs 全章均值
    try:
        from dramatic_arc_diagnostics import compute_drama_trends
        trends = compute_drama_trends(PROJECT_DIR)
        if trends.chapters and len(trends.chapters) >= 2:
            avg = trends.avg_pressure + trends.avg_arc + trends.avg_cinematic
            # trends avg are per-dimension averages; overall avg across chapters
            overall_avg = sum(s.overall_drama_score for s in trends.chapters if not s.is_mock)
            real_count = sum(1 for s in trends.chapters if not s.is_mock)
            overall_avg = overall_avg / real_count if real_count else 0
            current = drama.get("overall_drama_score", 0) if drama else 0
            diff = int(current - overall_avg) if current else 0
            arrow = "↑" if diff > 0 else ("↓" if diff < 0 else "→")
            st.caption(f"全章均值 {overall_avg:.0f}  |  当前 {current} {arrow}{abs(diff)}")
    except Exception:
        import sys
        print("[调试] 戏剧趋势迷你面板计算失败", file=sys.stderr)


def _render_drama_revision_targets(
    chapter_num: int,
    ch: str,
    drama: dict,
    mock_mode: bool,
) -> None:
    """渲染 top_revision_targets，每条带「采纳此改法」按钮。"""
    targets = drama.get("top_revision_targets", [])
    if not targets:
        st.caption("暂无改稿建议（诊断分数较高）")
        return

    llm_lock = is_llm_running(st.session_state)

    for i, target in enumerate(targets):
        with st.container(border=True):
            st.markdown(f"_{target}_")
            if st.button(
                "采纳此改法",
                key=f"adopt_drama_{ch}_{i}",
                disabled=llm_lock,
                use_container_width=True,
                type="secondary",
            ):
                _run_targeted_revision(chapter_num, target, mock_mode)


def _run_targeted_revision(chapter_num: int, target: str, mock: bool) -> None:
    """执行单条戏剧改稿建议 → 生成可一键采用的 inline diff。"""
    prompt = (
        "## 戏剧诊断改稿任务（结构保守）\n\n"
        f"{target}\n\n"
        "## 约束\n"
        "- 只改上述建议涉及的段落或句子，不改其他段落\n"
        "- 全文长度变化 ±5% 以内\n"
        "- 保留所有人物名字、伏笔标记、场景事实\n"
        "- 直接输出完整章节正文，不要任何元说明"
    )

    def work(cancel_event):
        path = run_writing_assist(
            chapter_num,
            "好看度精修",
            user_request=prompt,
            mock=mock,
        )
        if cancel_event.is_set():
            return None
        source_rel, original = latest_chapter_text(ch_str(chapter_num))
        revised = extract_adoptable_assist_text(path.read_text(encoding="utf-8")).strip()
        return {
            "ch": ch_str(chapter_num),
            "source_rel": source_rel,
            "original": original,
            "revised": revised,
            "reason": f"戏剧改稿：{target[:80]}",
        }

    def done(result):
        if not result:
            return
        _store_inline_revision_preview(
            result["ch"],
            result["source_rel"],
            result["original"],
            result["revised"],
            result["reason"],
        )
        st.success("已生成可逐块裁决的 inline diff。")

    _start_llm_background_job(
        "戏剧改稿 inline diff",
        work,
        eta_seconds=90,
        on_success=done,
    )


def _render_sub_reports(ch: str) -> None:
    """折叠区：四种审核报告。"""
    r1, r2, r3, r4 = st.tabs(["逻辑审计", "AI味检查", "读者镜像", "深度检查"])
    _report_tab(r1, f"04_审核日志/第{ch}章_审计.md", f"04_审核日志/第{ch}章_复审.md")
    _report_tab(r2, f"04_审核日志/第{ch}章_AI味检查.md")
    _report_tab(r3, f"04_审核日志/第{ch}章_读者镜像.md")
    _report_tab(r4, f"04_审核日志/第{ch}章_深度检查.md")


def _report_tab(tab_ctx, primary_rel: str, secondary_rel: str = "") -> None:
    with tab_ctx:
        text = read_file(primary_rel)
        if text:
            st.markdown(text)
        else:
            st.info("暂无报告")
        if secondary_rel:
            extra = read_file(secondary_rel)
            if extra:
                st.divider()
                st.subheader("修订后复审")
                st.markdown(extra)


def _render_quality_detail(quality: dict) -> None:
    """质量诊断数据表详情（低频，放折叠区）。"""
    metrics = quality.get("metrics", {})
    rows = [
        {"维度": "冲突信号", "数值": metrics.get("conflict_signal_density_per_1k", 0), "单位": "每千字"},
        {"维度": "角色主动性", "数值": metrics.get("agency_signal_density_per_1k", 0), "单位": "每千字"},
        {"维度": "可感细节", "数值": metrics.get("sensory_detail_density_per_1k", 0), "单位": "每千字"},
        {"维度": "身体化情绪", "数值": metrics.get("body_emotion_density_per_1k", 0), "单位": "每千字"},
        {"维度": "异常/线索", "数值": metrics.get("intrigue_signal_density_per_1k", 0), "单位": "每千字"},
        {"维度": "说明性句子", "数值": f"{float(metrics.get('exposition_sentence_ratio', 0)):.1%}", "单位": "占比"},
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)
    polish = quality.get("polish_targets", [])
    if polish:
        st.subheader("重点精修片段")
        st.dataframe(polish, use_container_width=True, hide_index=True)

    findings = quality.get("findings", [])
    if findings:
        st.subheader("诊断建议")
        chapter_num = int(quality.get("chapter_number", 0) or 0)

        # V5.0-rc1: 快速摘要（已裁决数量）
        active = [f for f in findings if isinstance(f, dict) and f.get("level") not in ("accepted_by_writer", "rebutted_by_writer")]
        adjudicated = [f for f in findings if isinstance(f, dict) and f.get("level") in ("accepted_by_writer", "rebutted_by_writer") or f.get("writer_action") in ("adopt",)]
        if adjudicated:
            protected = sum(1 for f in adjudicated if f.get("writer_action") == "protect" or f.get("level") == "accepted_by_writer")
            rebutted = sum(1 for f in adjudicated if f.get("writer_action") == "rebut" or f.get("level") == "rebutted_by_writer")
            adopted = sum(1 for f in adjudicated if f.get("writer_action") == "adopt")
            parts = []
            if adopted: parts.append(f"{adopted} 条已采纳")
            if protected: parts.append(f"{protected} 条已保护")
            if rebutted: parts.append(f"{rebutted} 条已反驳")
            st.caption(" · ".join(parts) + f"  |  {len(active)} 条待裁决")

        # 裁决面板（覆盖所有 findings，含已裁决项）
        from webui_infra.components.adjudication import render_adjudication_panel

        render_adjudication_panel(PROJECT_DIR, chapter_num, findings, source_label="质量诊断")

        # 旧详情列表（保留已裁决项展示，未裁决项简化）
        for idx, finding in enumerate(findings):
            if not isinstance(finding, dict):
                continue
            item = finding.get("item", "诊断建议")
            level = finding.get("level", "info")
            writer_action = finding.get("writer_action", "")
            writer_reason = finding.get("writer_reason", "")
            if writer_action in ("protect", "rebut", "adopt") or level in ("accepted_by_writer", "rebutted_by_writer"):
                continue  # 已在上方裁决面板展示
            # 未裁决项保留在旧位置供 judge
            with st.container(border=True):
                st.markdown(f"**[{level}] {item}**")
                st.caption(finding.get("detail", ""))


# ─────────────────────────────────────────────────────────────────────────────
# V3.1 文风样本池管理
# ─────────────────────────────────────────────────────────────────────────────

def _render_sample_pool_management() -> None:
    """渲染文风样本池：查看条目、锁定/排除 toggle。"""
    try:
        from sample_pool import load_pool, lock_sample, unlock_sample, exclude_sample, include_sample
    except Exception:
        st.caption("样本池模块不可用")
        return

    pool = load_pool(PROJECT_DIR)
    if not pool:
        st.caption("样本池为空 — 定稿并获得高分戏剧诊断（≥80）后自动入池")
        return

    st.caption(f"共 {len(pool)} 条  |  锁定 = 始终注入  |  排除 = 永不注入")

    for i, entry in enumerate(pool):
        locked_key = f"sample_lock_{i}"
        excluded_key = f"sample_excl_{i}"
        with st.container():
            c1, c2, c3 = st.columns([6, 1, 1])
            c1.markdown(
                f"**#{i+1}** 第{entry.source_chapter:03d}章（{entry.cinematic_score}分）\n\n"
                f"{entry.text[:120]}..."
            )
            curr_locked = entry.locked
            curr_excluded = entry.excluded

            new_locked = c2.toggle("锁", value=curr_locked, key=locked_key,
                                   help="锁定后始终注入")
            new_excluded = c3.toggle("排", value=curr_excluded, key=excluded_key,
                                     help="排除后永不注入")

            if new_locked != curr_locked:
                if new_locked:
                    lock_sample(PROJECT_DIR, i)
                else:
                    unlock_sample(PROJECT_DIR, i)
                st.rerun()

            if new_excluded != curr_excluded:
                if new_excluded:
                    exclude_sample(PROJECT_DIR, i)
                else:
                    include_sample(PROJECT_DIR, i)
                st.rerun()
