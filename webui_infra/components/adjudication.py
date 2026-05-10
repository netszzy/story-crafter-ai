"""V5.0-rc1 统一作家裁决面板 — 每条诊断的三态裁决（采纳 / 保护 / 反驳）。"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st


def render_adjudication_panel(
    project_dir: str | Path,
    chapter_num: int,
    findings: list[dict[str, Any]],
    *,
    source_label: str = "诊断建议",
    mock_mode: bool = False,
) -> None:
    """统一裁决面板：每条 finding 提供 adopt / protect / rebut 三态按钮。

    裁决写入 04_审核日志/第{chapter_num}章_诊断豁免.json，跨会话持久化。
    """
    if not chapter_num or not findings:
        return


    with st.container(border=True):
        st.markdown(f"**{source_label}**（作家裁决）")
        st.caption("采纳 = 同意诊断，下次改稿执行 · 保护 = 保留文本不修 · 反驳 = 诊断有误")

        for idx, finding in enumerate(findings):
            item = finding.get("item") or finding.get("issue") or finding.get("rejected_advice") or "未命名"
            level = finding.get("level", "info")
            detail = finding.get("detail") or finding.get("issue") or ""
            writer_action = finding.get("writer_action", "")
            writer_reason = finding.get("writer_reason", "")

            # 已有裁决状态
            if writer_action in ("protect",):
                _render_adjudicated_row(item, detail, "protect", writer_reason)
                continue
            if writer_action == "rebut":
                _render_adjudicated_row(item, detail, "rebut", writer_reason)
                continue
            if writer_action == "adopt":
                _render_adjudicated_row(item, detail, "adopt", writer_reason)
                continue

            # 未裁决项
            with st.container():
                st.markdown(
                    f"<small>[{level.upper()}]</small> **{item}**",
                    unsafe_allow_html=True,
                )
                if detail:
                    st.caption(detail)

                col_adopt, col_protect, col_rebut = st.columns(3, gap="small")

                # 采纳按钮
                adopt_key = f"adj_adopt_{chapter_num}_{idx}_{abs(hash(item))}"
                if col_adopt.button(
                    "采纳 · 下次改", key=adopt_key, use_container_width=True,
                    help="同意此诊断，下次改稿时执行",
                ):
                    _write_adjudication(project_dir, chapter_num, finding, "adopt", "作家采纳此诊断，将在下次改稿时处理。")
                    st.rerun()

                # 保护按钮
                protect_key = f"adj_protect_{chapter_num}_{idx}_{abs(hash(item))}"
                protect_popover = col_protect.popover("保护 · 不改", key=protect_key, use_container_width=True)
                with protect_popover:
                    st.caption("保护理由（为什么保留当前写法）：")
                    reason = st.text_area(
                        "理由",
                        key=f"adj_protect_reason_{chapter_num}_{idx}",
                        placeholder="例如：本章是氛围章，这里的沉默是刻意保留的。",
                        label_visibility="collapsed",
                        height=68,
                    )
                    if st.button("确认保护", key=f"adj_protect_confirm_{chapter_num}_{idx}", use_container_width=True):
                        if not reason.strip():
                            st.warning("请写一句保护理由。")
                        else:
                            _write_adjudication(project_dir, chapter_num, finding, "protect", reason.strip())
                            st.success("已保护此建议，不再进入改稿清单。")
                            st.rerun()

                # 反驳按钮
                rebut_key = f"adj_rebut_{chapter_num}_{idx}_{abs(hash(item))}"
                rebut_popover = col_rebut.popover("反驳 · 误判", key=rebut_key, use_container_width=True)
                with rebut_popover:
                    st.caption("反驳理由（为什么这条诊断判断有误）：")
                    reason = st.text_area(
                        "理由",
                        key=f"adj_rebut_reason_{chapter_num}_{idx}",
                        placeholder="例如：这处冲突是通过对话间接表达的，诊断器未识别。",
                        label_visibility="collapsed",
                        height=68,
                    )
                    if st.button("确认反驳", key=f"adj_rebut_confirm_{chapter_num}_{idx}", use_container_width=True):
                        if not reason.strip():
                            st.warning("反驳理由不能为空。")
                        else:
                            _write_adjudication(project_dir, chapter_num, finding, "rebut", reason.strip())
                            st.success("已反驳此诊断，不再进入改稿和诊断清单。")
                            st.rerun()


def _write_adjudication(
    project_dir: str | Path,
    chapter_num: int,
    finding: dict[str, Any],
    action: str,
    reason: str,
) -> None:
    """写入裁决记录到诊断豁免 JSON。"""
    from quality_diagnostics import write_writer_override

    item = finding.get("item") or finding.get("issue") or finding.get("rejected_advice") or ""
    diagnostic_source = str(finding.get("diagnostic_source") or finding.get("source") or "quality")
    finding_key = str(finding.get("finding_key") or f"{diagnostic_source}:{item}")

    write_writer_override(
        project_dir,
        chapter_num,
        rejected_advice=item,
        writer_reason=reason,
        diagnostic_source=diagnostic_source,
        finding_key=finding_key,
        action=action,
    )


def _render_adjudicated_row(
    item: str,
    detail: str,
    action: str,
    reason: str,
) -> None:
    """渲染已裁决的 finding 行。"""
    action_labels = {"adopt": "已采纳", "protect": "已保护", "rebut": "已反驳"}
    action_colors = {
        "adopt": "var(--brand-primary)",
        "protect": "var(--text-muted)",
        "rebut": "var(--status-bad)",
    }
    label = action_labels.get(action, action)
    color = action_colors.get(action, "var(--text-muted)")

    st.markdown(
        f"<small style='color:{color}'>[{label.upper()}]</small> **{item}** "
        f"<small style='color:var(--novel-muted);'>{reason[:80]}</small>",
        unsafe_allow_html=True,
    )
