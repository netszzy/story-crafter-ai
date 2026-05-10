"""
V5.0 编辑备忘录合成器。

把多项独立诊断（戏剧/质量/审计/读者镜像/文学批评/风格法庭）合成为一份
聚焦的「编辑备忘录」，去重、排序、标矛盾、给执行指令。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from novel_schemas import (
    DiagnosticReservation,
    DramaticDiagnostics,
    EditorMemo,
    LiteraryView,
    MemoItem,
    StyleCourtDecision,
    model_to_json,
)
from style_court import _is_mock_caveat


PROMPT_REL = "prompts/编辑备忘录.md"
DEFAULT_LABELS = {
    "drama": "戏剧",
    "quality": "质量",
    "audit": "审计",
    "reader": "读者",
}
LITERARY_PROTECTION_TERMS = [
    "冲突", "主动性", "agency", "身体", "身体情绪", "动作", "行动", "压力", "代价", "选择",
    "追读", "钩子", "抓力", "欲望", "恐惧", "反击",
]


def synthesize_memo(
    project_dir: Path,
    chapter_num: int,
    chapter_text: str,
    *,
    audit_text: str = "",
    reader_mirror_text: str = "",
    quality_report: dict[str, Any] | None = None,
    drama_diag: DramaticDiagnostics | None = None,
    literary_view: LiteraryView | None = None,
    style_court_decision: StyleCourtDecision | None = None,
    llm: Any | None = None,
) -> EditorMemo:
    """主入口：接收所有诊断输出，调用 CRITIC_PROVIDER 合成编辑备忘录。"""
    project_dir = Path(project_dir)
    if llm is None:
        from llm_router import LLMRouter
        llm = LLMRouter(project_dir=project_dir)

    meta = _chapter_memo_meta(project_dir, chapter_num)
    meta["reservations"] = _merge_reservations(
        meta.get("reservations", []),
        literary_view=literary_view,
        style_court_decision=style_court_decision,
    )
    if _should_mock(llm):
        return _fallback_memo(
            chapter_num,
            quality_report,
            drama_diag,
            audit_text,
            style_profile=meta.get("style_profile", ""),
            chapter_mode=meta.get("chapter_mode", ""),
            reservations=meta.get("reservations", []),
            literary_view=literary_view,
            style_court_decision=style_court_decision,
        )

    system_prompt = _build_system_prompt(project_dir)
    user_msg = _build_user_msg(
        chapter_text, audit_text,
        reader_mirror_text, quality_report, drama_diag, meta,
        literary_view=literary_view, style_court_decision=style_court_decision,
    )

    raw = llm.critic_text(
        system_prompt=system_prompt,
        user_prompt=user_msg,
        workflow="editor-memo",
        role="editor-memo",
        max_tokens=2000,
    )
    return _parse_memo_response(
        raw, chapter_num, llm, quality_report, drama_diag, audit_text, meta,
        literary_view=literary_view, style_court_decision=style_court_decision,
    )


def write_memo(project_dir: Path, memo: EditorMemo) -> tuple[Path, Path]:
    """写入 04_审核日志/第{ch}章_编辑备忘录.json + .md，返回两个路径。"""
    project_dir = Path(project_dir)
    ch = f"{memo.chapter_number:03d}"
    log_dir = project_dir / "04_审核日志"
    json_path = log_dir / f"第{ch}章_编辑备忘录.json"
    md_path = log_dir / f"第{ch}章_编辑备忘录.md"
    log_dir.mkdir(parents=True, exist_ok=True)
    json_path.write_text(model_to_json(memo) + "\n", encoding="utf-8")
    md_path.write_text(_render_memo_markdown(memo), encoding="utf-8")
    return md_path, json_path


def read_memo(project_dir: Path, chapter_num: int) -> EditorMemo | None:
    path = Path(project_dir) / "04_审核日志" / f"第{chapter_num:03d}章_编辑备忘录.json"
    if not path.exists():
        return None
    try:
        return EditorMemo.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValidationError):
        return None


def memo_to_revision_prompt(memo: EditorMemo) -> str:
    """将备忘录转成给 reviser 的精简改稿指令。"""
    if not memo.top_3_must_fix:
        return "## 编辑备忘录\n\n暂无必改项，保持当前版本。"

    lines = [
        "## 编辑备忘录（优先级改稿指令）",
        "",
        f"整体评估：{memo.overall_assessment or '请按下方 P0/P1 项修改'}",
        *([f"章节模式：{memo.chapter_mode}"] if memo.chapter_mode else []),
        *([f"风格档案：{memo.style_profile}"] if memo.style_profile else []),
        "",
        "### 必改项",
    ]
    for idx, item in enumerate(memo.top_3_must_fix, start=1):
        lines.append(
            f"{idx}. **[{item.priority}]** {item.issue}\n"
            f"   位置：{item.location}\n"
            f"   改法：{item.action}\n"
            f"   验收：{item.acceptance}"
        )

    if memo.contradictions:
        lines.append("\n### 注意：诊断间矛盾")
        for c in memo.contradictions:
            lines.append(f"- {c}")

    if memo.reservations:
        lines.append("\n### 作家已拒绝/保护的诊断（禁止执行）")
        for item in memo.reservations:
            lines.append(
                f"- 不要执行「{item.rejected_advice}」（来源：{item.diagnostic_source}）。"
                f"作家理由：{item.writer_reason}"
            )

    scores = memo.score_summary
    if scores:
        parts = [f"{DEFAULT_LABELS.get(k, k)}:{v}" for k, v in scores.items()]
        lines.append(f"\n评分摘要：{'  '.join(parts)}")

    lines.extend([
        "",
        "### 改稿约束",
        "- 不改核心剧情，不新增与项目轴冲突的新事实。",
        "- 优先修复 P0 项，P1/P2 项尽量修复但不以破坏节奏为代价。",
        "- 原文中的留白、停顿、未说完的话、未解状态必须保留——不要为了'让段落完整'而补全，"
        "不要为了'让信息更清楚'而展开解释。",
        "- 不要为了过冲突信号、主动性、感官词等指标而强行加冲突词、动作或形容词。",
        "- 只动备忘录点名的局部，其他段落原样保留。",
    ])
    return "\n".join(lines).strip()


# ── private ──────────────────────────────────────────────────────────────────


def _build_system_prompt(project_dir: Path) -> str:
    template_path = Path(project_dir) / PROMPT_REL
    if not template_path.exists():
        template_path = Path(__file__).resolve().parent / PROMPT_REL
    template = template_path.read_text(encoding="utf-8") if template_path.exists() else ""
    schema = json.dumps(EditorMemo.model_json_schema(), ensure_ascii=False, indent=2)
    return template.replace("{{ json_schema }}", schema).strip()


def _build_user_msg(
    chapter_text: str,
    audit_text: str,
    reader_mirror_text: str,
    quality_report: dict[str, Any] | None,
    drama_diag: DramaticDiagnostics | None,
    meta: dict[str, Any] | None = None,
    *,
    literary_view: LiteraryView | None = None,
    style_court_decision: StyleCourtDecision | None = None,
) -> str:
    blocks: list[str] = []
    meta = meta or {}
    reservations = meta.get("reservations", [])
    if meta.get("chapter_mode") or meta.get("style_profile") or reservations:
        lines = ["## 本章诊断保留上下文"]
        if meta.get("chapter_mode"):
            lines.append(f"- chapter_mode：{meta['chapter_mode']}")
        if meta.get("style_profile"):
            lines.append(f"- style_profile：{meta['style_profile']}")
        if reservations:
            lines.append("### 作家已拒绝/保护的诊断")
            for item in reservations:
                lines.append(
                    f"- [{item.get('diagnostic_source', 'quality')}] {item.get('rejected_advice', '')}："
                    f"{item.get('writer_reason', '')}"
                )
        blocks.append("\n".join(lines))

    if drama_diag is not None:
        blocks.append(
            f"## 戏剧诊断\n"
            f"- 压力曲线：{drama_diag.pressure_curve_score}/100\n"
            f"- 人物弧光：{drama_diag.character_arc_score}/100\n"
            f"- 画面可视性：{drama_diag.cinematic_score}/100\n"
            f"- 综合：{drama_diag.overall_drama_score}/100\n"
            f"### 改稿目标\n" +
            "\n".join(f"- {t}" for t in drama_diag.top_revision_targets[:5])
        )

    if quality_report:
        score = quality_report.get("score", 0)
        grade = quality_report.get("grade", "")
        findings = [
            f for f in quality_report.get("findings", [])
            if isinstance(f, dict) and f.get("level") != "accepted_by_writer"
        ]
        finding_lines = "\n".join(
            f"- [{f.get('level', 'info')}] {f.get('item', '')}: {f.get('detail', '')}"
            for f in findings[:5]
        )
        blocks.append(
            f"## 质量诊断\n"
            f"- 评分：{score}/100（{grade}）\n"
            f"### 发现\n{finding_lines}"
        )

    if literary_view is not None:
        moment_lines = "\n".join(
            f"- 「{m.quote}」：{m.why_memorable}；脆弱处：{m.fragility}"
            for m in literary_view.memorable_moments[:5]
        ) or "- （无）"
        risk_lines = "\n".join(f"- {item}" for item in literary_view.literary_risks[:6]) or "- （无）"
        residue_lines = "\n".join(f"- {item}" for item in literary_view.reader_residue[:4]) or "- （无）"
        blocks.append(
            "## 文学批评层（不参与打分）\n"
            f"- 不可量化保护：{'是' if literary_view.cannot_be_quantified else '否'}\n"
            f"- Mock：{'是' if literary_view.is_mock else '否'}\n"
            f"### 可被记住的瞬间\n{moment_lines}\n"
            f"### 读者残响\n{residue_lines}\n"
            f"### 文学风险（不得进入 must_fix，应进入 reservations）\n{risk_lines}"
        )

    if style_court_decision is not None:
        confirmed = "\n".join(
            f"- [{item.source}] {item.issue}：{item.reason}"
            for item in style_court_decision.confirmed_issues[:8]
        ) or "- （无）"
        contested = "\n".join(
            f"- [{item.source}] {item.issue}：{item.reason}"
            for item in style_court_decision.contested_issues[:8]
        ) or "- （无）"
        priorities = "\n".join(
            f"- {item}" for item in style_court_decision.literary_priorities[:6]
        ) or "- （无）"
        blocks.append(
            "## 风格法庭裁决\n"
            "规则：confirmed 可进入 top_3_must_fix；contested 必须进入 reservations，不得换说法继续要求执行。\n"
            f"### confirmed_issues\n{confirmed}\n"
            f"### contested_issues\n{contested}\n"
            f"### literary_priorities\n{priorities}"
        )

    if audit_text.strip():
        excerpt = audit_text[:800] + ("..." if len(audit_text) > 800 else "")
        blocks.append(f"## 逻辑审计\n{excerpt}")

    if reader_mirror_text.strip():
        excerpt = reader_mirror_text[:800] + ("..." if len(reader_mirror_text) > 800 else "")
        # 读者镜像降级为参考层：可作为风格法庭的输入参考，但不得直接生成 P0 必改项。
        blocks.append(
            "## 读者镜像（参考层）\n"
            "> 仅作风格法庭的参考输入，不得直接产生 top_3_must_fix；除非和 confirmed_issues 重合，否则进入 reservations。\n\n"
            f"{excerpt}"
        )

    return "\n\n".join(blocks)


def _parse_memo_response(
    raw: str,
    chapter_num: int,
    llm: Any,
    quality_report: dict[str, Any] | None = None,
    drama_diag: DramaticDiagnostics | None = None,
    audit_text: str = "",
    meta: dict[str, Any] | None = None,
    literary_view: LiteraryView | None = None,
    style_court_decision: StyleCourtDecision | None = None,
) -> EditorMemo:
    meta = meta or {}
    try:
        payload = _extract_json_object(raw)
        data = json.loads(payload)
        data.setdefault("chapter_number", chapter_num)
        data.setdefault("style_profile", meta.get("style_profile", ""))
        data.setdefault("chapter_mode", meta.get("chapter_mode", ""))
        data.setdefault("reservations", meta.get("reservations", []))
        data["reservations"] = _merge_reservations(
            data.get("reservations", []),
            literary_view=literary_view,
            style_court_decision=style_court_decision,
        )
        if llm is not None:
            data.setdefault("provider_used", getattr(llm, "CRITIC_PROVIDER", ""))
            data.setdefault("model_used", _memo_model_name(llm))
        memo = EditorMemo.model_validate(data)
        return memo
    except (ValueError, json.JSONDecodeError, ValidationError):
        return _fallback_memo(
            chapter_num,
            quality_report,
            drama_diag,
            audit_text,
            style_profile=meta.get("style_profile", ""),
            chapter_mode=meta.get("chapter_mode", ""),
            reservations=meta.get("reservations", []),
            literary_view=literary_view,
            style_court_decision=style_court_decision,
        )


def _fallback_memo(
    chapter_num: int,
    quality_report: dict[str, Any] | None = None,
    drama_diag: DramaticDiagnostics | None = None,
    audit_text: str = "",
    style_profile: str = "",
    chapter_mode: str = "",
    reservations: list[dict[str, Any]] | None = None,
    literary_view: LiteraryView | None = None,
    style_court_decision: StyleCourtDecision | None = None,
) -> EditorMemo:
    """零 API 成本降级：从各诊断抽取 top 问题合并。"""
    items: list[MemoItem] = []
    scores: dict[str, int] = {}
    contradictions: list[str] = []
    reservation_rows = _merge_reservations(
        reservations or [],
        literary_view=literary_view,
        style_court_decision=style_court_decision,
    )

    # 从戏剧诊断取 top targets
    if drama_diag is not None:
        scores["drama"] = drama_diag.overall_drama_score
        for target in drama_diag.top_revision_targets[:2]:
            if _protected_by_literary_context(target, literary_view, style_court_decision):
                continue
            items.append(MemoItem(
                priority="P1",
                source="drama",
                issue=target[:120] if len(target) > 120 else target,
                action=target,
            ))

    # 从质量诊断取 findings
    if quality_report:
        scores["quality"] = quality_report.get("score", 0)
        active_findings = [
            item for item in quality_report.get("findings", [])
            if isinstance(item, dict) and item.get("level") != "accepted_by_writer"
        ]
        quality_added = 0
        for finding in active_findings:
            if _finding_contested_by_style_court(finding, style_court_decision):
                continue
            level = finding.get("level", "info")
            prio = "P0" if level == "error" else ("P1" if level == "warning" else "P2")
            items.append(MemoItem(
                priority=prio,
                source="quality",
                issue=finding.get("item", ""),
                action=finding.get("detail", ""),
            ))
            quality_added += 1
            if quality_added >= 2:
                break

    # 从审计取第一条 actionable 问题
    if audit_text and "【问题位置】" in audit_text:
        lines = audit_text.splitlines()
        for line in lines:
            if "【问题位置】" in line or "问题" in line[:4]:
                items.append(MemoItem(
                    priority="P0",
                    source="audit",
                    issue=line[:120],
                    action="见审计报告全文",
                ))
                break

    # 去重排序：按 priority 排序
    prio_order = {"P0": 0, "P1": 1, "P2": 2}
    seen = set()
    unique: list[MemoItem] = []
    for item in sorted(items, key=lambda i: prio_order.get(i.priority, 2)):
        if item.priority != "P0" and _protected_by_literary_context(item.issue + item.action, literary_view, style_court_decision):
            continue
        key = item.issue[:60]
        if key not in seen:
            seen.add(key)
            unique.append(item)

    # 交叉矛盾检测
    if drama_diag and quality_report:
        d_score = drama_diag.overall_drama_score
        q_score = quality_report.get("score", 0)
        if d_score >= 70 and q_score < 55:
            contradictions.append("戏剧诊断给分较高，但质量诊断认为存在较多问题。请人工判断：是否戏剧评估过松？")
        elif q_score >= 70 and d_score < 55:
            contradictions.append("质量诊断给分较高，但戏剧诊断认为结构存在短板。请人工判断：是否语言层好但故事层弱？")

    ready = len(unique) == 0 or all(i.priority != "P0" for i in unique)
    overall = "[Mock] " + ("质量整体较好，少量优化后即可定稿。" if ready else "有必改项需要处理后再定稿。")

    return EditorMemo(
        chapter_number=chapter_num,
        style_profile=style_profile,
        chapter_mode=chapter_mode,
        reservations=[DiagnosticReservation.model_validate(item) for item in reservation_rows],
        model_used="mock-editor-memo",
        provider_used="mock",
        top_3_must_fix=unique[:3],
        contradictions=contradictions,
        score_summary=scores,
        ready_to_finalize=ready,
        overall_assessment=overall,
        is_mock=True,
    )


def _render_memo_markdown(memo: EditorMemo) -> str:
    lines = [
        f"# 第{memo.chapter_number:03d}章 编辑备忘录",
        "",
        f"- 模型：{memo.provider_used}/{memo.model_used}",
        f"- Mock：{'是' if memo.is_mock else '否'}",
        f"- 章节模式：{memo.chapter_mode or '未指定'}",
        f"- 风格档案：{memo.style_profile or '未指定'}",
        f"- 定稿就绪：{'是' if memo.ready_to_finalize else '否'}",
        f"- 整体评估：{memo.overall_assessment}",
        "",
    ]
    literary_reservations = [
        item for item in memo.reservations
        if item.diagnostic_source in {"literary", "style_court"} or "文学" in item.writer_reason
    ]
    if literary_reservations:
        lines += ["## 文学保护 / 风格法庭", ""]
        for item in literary_reservations:
            lines.append(f"- [{item.diagnostic_source}] {item.rejected_advice}：{item.writer_reason}")
        lines.append("")

    lines.append("## 评分摘要")
    for k, v in memo.score_summary.items():
        lines.append(f"- {DEFAULT_LABELS.get(k, k)}：{v}")
    lines.append("")
    lines.append("## 必改项")
    for idx, item in enumerate(memo.top_3_must_fix, start=1):
        lines.append(
            f"### {idx}. [{item.priority}] {item.issue}\n\n"
            f"- 来源：{item.source}\n"
            f"- 位置：{item.location}\n"
            f"- 改法：{item.action}\n"
            f"- 验收：{item.acceptance}\n"
        )
    if memo.contradictions:
        lines.append("## 诊断间矛盾")
        for c in memo.contradictions:
            lines.append(f"- {c}")
    if memo.reservations:
        lines.append("")
        lines.append("## 作家豁免")
        for item in memo.reservations:
            lines.append(f"- [{item.diagnostic_source}] {item.rejected_advice}：{item.writer_reason}")
    return "\n".join(lines).strip() + "\n"


def _merge_reservations(
    reservations: list[dict[str, Any]] | list[DiagnosticReservation] | None,
    *,
    literary_view: LiteraryView | None = None,
    style_court_decision: StyleCourtDecision | None = None,
) -> list[dict[str, Any]]:
    """合并作家裁决、文学风险和风格法庭 contested 为阻止改稿的 reservations。

    V5.0-rc1: 只保留 action=protect/rebut 的裁决；adopt 不进 reservations。
    旧记录缺 action 字段时默认视为 protect。
    """
    rows: list[dict[str, Any]] = []

    for item in reservations or []:
        entry: dict[str, Any] = item.model_dump() if isinstance(item, DiagnosticReservation) else dict(item)
        action = str(entry.get("action", "protect") or "protect").strip()
        if action == "adopt":
            continue
        rows.append(entry)

    if literary_view is not None:
        for risk in literary_view.literary_risks:
            if not risk:
                continue
            if _is_mock_caveat(risk):
                continue
            rows.append({
                "action": "protect",
                "diagnostic_source": "literary",
                "rejected_advice": risk,
                "writer_reason": "文学批评层提示该建议可能损伤克制、氛围、残响或未说之语。",
                "finding_key": "",
            })

    if style_court_decision is not None:
        for issue in style_court_decision.contested_issues:
            rows.append({
                "action": "protect",
                "diagnostic_source": issue.source or "style_court",
                "rejected_advice": issue.issue,
                "writer_reason": issue.reason,
                "finding_key": issue.finding_key,
            })

    seen: set[str] = set()
    merged: list[dict[str, Any]] = []
    for row in rows:
        source = str(row.get("diagnostic_source", "") or "")
        advice = str(row.get("rejected_advice", "") or "")
        key = str(row.get("finding_key", "") or "")
        if not advice:
            continue
        dedupe_key = f"{source}:{key}:{advice[:120]}"
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        merged.append(row)
    return merged


def _finding_contested_by_style_court(
    finding: dict[str, Any],
    style_court_decision: StyleCourtDecision | None,
) -> bool:
    if style_court_decision is None:
        return False
    key = str(finding.get("finding_key", "") or "")
    item = str(finding.get("item", "") or "")
    detail = str(finding.get("detail", "") or "")
    text = f"{item}：{detail}" if detail else item
    for issue in style_court_decision.contested_issues:
        if key and issue.finding_key and key == issue.finding_key:
            return True
        issue_text = issue.issue or ""
        if item and (item in issue_text or issue_text in text):
            return True
    return False


def _protected_by_literary_context(
    text: str,
    literary_view: LiteraryView | None,
    style_court_decision: StyleCourtDecision | None,
) -> bool:
    if not text:
        return False
    has_literary_protection = bool(
        literary_view
        and literary_view.cannot_be_quantified
        and (literary_view.literary_risks or literary_view.memorable_moments)
    )
    has_court_contested = bool(style_court_decision and style_court_decision.contested_issues)
    if not (has_literary_protection or has_court_contested):
        return False
    return any(term in text for term in LITERARY_PROTECTION_TERMS)



def _chapter_memo_meta(project_dir: Path, chapter_num: int) -> dict[str, Any]:
    meta: dict[str, Any] = {"style_profile": "", "chapter_mode": "", "reservations": []}
    try:
        from structured_store import read_task_card

        card = read_task_card(project_dir, chapter_num)
        if card is not None:
            meta["style_profile"] = card.style_profile
            meta["chapter_mode"] = card.chapter_mode
    except Exception:
        pass
    try:
        from quality_diagnostics import read_writer_overrides

        meta["reservations"] = read_writer_overrides(project_dir, chapter_num)
    except Exception:
        pass
    return meta


def _extract_json_object(raw: str) -> str:
    text = (raw or "").strip()
    fence = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
    if fence:
        return fence.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("No JSON object found in editor memo response")
    return text[start : end + 1]


def _should_mock(llm: Any) -> bool:
    if not hasattr(llm, "critic_text"):
        return True
    mode = str(getattr(llm, "mode", "auto")).lower()
    if mode == "mock":
        return True
    if mode == "real":
        return False
    provider = str(getattr(llm, "CRITIC_PROVIDER", "deepseek")).lower()
    if provider == "openrouter":
        return bool(getattr(llm, "_should_mock", lambda p, k: True)("openrouter", "OPENROUTER_API_KEY"))
    return bool(getattr(llm, "_should_mock", lambda p, k: True)("deepseek", "DEEPSEEK_API_KEY"))


def _memo_model_name(llm: Any) -> str:
    provider = str(getattr(llm, "CRITIC_PROVIDER", "deepseek")).lower()
    if provider == "openrouter":
        return str(getattr(llm, "OPENROUTER_CRITIC_MODEL", ""))
    return str(getattr(llm, "DEEPSEEK_MODEL", ""))
