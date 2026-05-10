"""
novel_pipeline.py - 逐章生成与定稿记忆流水线

用法：
  python novel_pipeline.py --chapter 1
  python novel_pipeline.py --chapter 1 --mock
  python novel_pipeline.py --chapter 1 --audit-only
  python novel_pipeline.py --chapter 1 --finalize --yes --mock
  python novel_pipeline.py --reindex
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

from project_archive import archive_existing

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

PROJECT_DIR = Path(__file__).resolve().parent


def ch_str(chapter_num: int) -> str:
    return f"{chapter_num:03d}"


def load(rel_path: str) -> str:
    full = PROJECT_DIR / rel_path
    if not full.is_file():
        print(f"[警告] 文件不存在：{full}")
        return ""
    return full.read_text(encoding="utf-8")


def save(rel_path: str, content: str, preserve_existing: bool = True) -> Path:
    full = PROJECT_DIR / rel_path
    full.parent.mkdir(parents=True, exist_ok=True)
    if preserve_existing and full.exists():
        archive_existing(full)
    full.write_text(content, encoding="utf-8")
    return full


def word_count_zh(text: str) -> int:
    return sum(1 for c in text if "\u4e00" <= c <= "\u9fff")


def update_recent_summary(chapter_num: int, summary: str) -> None:
    path = PROJECT_DIR / "03_滚动记忆" / "最近摘要.md"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    blocks = [b for b in re.split(r"(?=## 第\d+章)", existing) if b.strip()]
    blocks = [b for b in blocks if re.match(r"## 第\d+章", b.strip())]
    blocks = [b for b in blocks if not re.match(fr"## 第0*{chapter_num}章", b.strip())]
    blocks.append(f"## 第{chapter_num}章\n\n{summary.strip()}\n")
    blocks = blocks[-3:]
    path.parent.mkdir(parents=True, exist_ok=True)
    header = "# 最近章节摘要\n\n（自动保留最近3章，每章约300字；定稿后可人工修订。）\n\n"
    path.write_text(header + "\n".join(blocks).strip() + "\n", encoding="utf-8")


def update_global_summary(chapter_num: int, summary: str) -> None:
    path = PROJECT_DIR / "03_滚动记忆" / "全局摘要.md"
    existing = path.read_text(encoding="utf-8") if path.exists() else "# 全局摘要\n\n"
    marker = f"<!-- auto-chapter-{chapter_num:03d} -->"
    entry = f"{marker}\n- 第{chapter_num:03d}章：{first_line(summary, 220)}\n"
    if marker in existing:
        existing = re.sub(fr"{re.escape(marker)}\n- 第{chapter_num:03d}章：.*(?:\n|$)", entry, existing)
    else:
        if not existing.endswith("\n"):
            existing += "\n"
        existing += "\n" + entry
    path.write_text(existing.strip() + "\n", encoding="utf-8")


def update_foreshadow_table(chapter_num: int, chapter_outline: str) -> None:
    path = PROJECT_DIR / "03_滚动记忆" / "伏笔追踪.md"
    content = path.read_text(encoding="utf-8") if path.exists() else default_foreshadow_table()
    content = ensure_foreshadow_table_columns(content)

    planted = extract_outline_items(chapter_outline, "埋下")
    resolved = extract_outline_items(chapter_outline, "收回")

    for item in planted:
        fid = extract_foreshadow_id(item) or next_foreshadow_id(content)
        if fid not in content:
            row = (
                f"| {fid} | 第{chapter_num:03d}章 | {cleanup_outline_item(item)} | "
                "🟡待回收 | 待定 | 章纲/任务卡 | V1.6 自动登记 |\n"
            )
            content = insert_table_row(content, row)

    for item in resolved:
        fid = extract_foreshadow_id(item)
        if fid:
            content = mark_foreshadow_resolved(content, fid)

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def update_character_state(chapter_num: int, summary: str) -> None:
    path = PROJECT_DIR / "03_滚动记忆" / "人物状态表.md"
    existing = path.read_text(encoding="utf-8") if path.exists() else "# 人物状态表\n"
    marker = f"<!-- auto-chapter-{chapter_num:03d} -->"
    block = (
        f"{marker}\n"
        f"## 第{chapter_num:03d}章后待确认状态\n"
        f"- 自动摘要：{first_line(summary, 260)}\n"
        "- 人工核对：位置、身体状态、情绪状态、获知信息、持有物品。\n"
    )
    if marker in existing:
        existing = re.sub(fr"{re.escape(marker)}[\s\S]*?(?=<!-- auto-chapter-|\Z)", block, existing)
    else:
        existing = existing.rstrip() + "\n\n" + block
    path.write_text(existing.strip() + "\n", encoding="utf-8")


def write_draft_summary(chapter_num: int, summary: str, source_rel: str) -> tuple[Path, Path]:
    """保存草稿阶段摘要；不进入滚动记忆，也不进入 RAG。

    草稿和自动修订稿仍可能被人工大改，提前进入长期记忆会污染后续章节上下文。
    """
    ch = ch_str(chapter_num)
    created_at = datetime.now().isoformat(timespec="seconds")
    clean_summary = summary.strip()
    md = (
        f"# 第{ch}章 草稿摘要\n\n"
        f"- 来源：`{source_rel}`\n"
        f"- 状态：草稿参考，不写入滚动记忆或 RAG。\n"
        f"- 生成时间：{created_at}\n\n"
        "## 摘要\n\n"
        f"{clean_summary}\n"
    )
    data = {
        "chapter_number": chapter_num,
        "source_markdown_path": source_rel,
        "summary": clean_summary,
        "status": "draft_only",
        "created_at": created_at,
    }
    md_path = save(f"04_审核日志/第{ch}章_草稿摘要.md", md)
    json_path = save(
        f"04_审核日志/第{ch}章_草稿摘要.json",
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
    )
    return md_path, json_path


def first_line(text: str, limit: int) -> str:
    compact = " ".join(text.split())
    return compact[:limit] + ("..." if len(compact) > limit else "")


def extract_outline_items(chapter_outline: str, label: str) -> list[str]:
    items: list[str] = []
    for line in chapter_outline.splitlines():
        stripped = line.strip()
        if label in stripped and not stripped.endswith("无"):
            _, _, tail = stripped.partition("：")
            items.append(tail.strip() or stripped)
    return items


def extract_foreshadow_id(text: str) -> str | None:
    match = re.search(r"F\d{3}", text, re.IGNORECASE)
    return match.group(0).upper() if match else None


def cleanup_outline_item(text: str) -> str:
    text = re.sub(r"【?F\d{3}】?", "", text, flags=re.IGNORECASE)
    return text.strip(" ：:，,；;") or "待补充伏笔内容"


def next_foreshadow_id(content: str) -> str:
    nums = [int(n) for n in re.findall(r"F(\d{3})", content, flags=re.IGNORECASE)]
    return f"F{(max(nums) + 1 if nums else 1):03d}"


def insert_table_row(content: str, row: str) -> str:
    lines = content.splitlines(keepends=True)
    for idx, line in enumerate(lines):
        if line.startswith("|") and "---" in line:
            lines.insert(idx + 1, row)
            return "".join(lines)
    return content.rstrip() + "\n\n" + default_foreshadow_table() + row


def mark_foreshadow_resolved(content: str, fid: str) -> str:
    new_lines = []
    for line in content.splitlines():
        if line.startswith("|") and fid in line:
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 5:
                cells[3] = "🟢已回收"
                line = "| " + " | ".join(cells) + " |"
        new_lines.append(line)
    return "\n".join(new_lines) + "\n"


def default_foreshadow_table() -> str:
    return (
        "# 伏笔追踪表\n\n"
        "| 编号 | 埋入章节 | 伏笔内容 | 状态 | 计划回收章节 | 来源 | 备注 |\n"
        "|------|---------|---------|------|------------|------|------|\n"
    )


def ensure_foreshadow_table_columns(content: str) -> str:
    if "| 来源 |" in content and "| 备注 |" in content:
        return content
    lines = content.splitlines()
    upgraded: list[str] = []
    for line in lines:
        if line.startswith("| 编号 |"):
            upgraded.append("| 编号 | 埋入章节 | 伏笔内容 | 状态 | 计划回收章节 | 来源 | 备注 |")
        elif line.startswith("|") and "---" in line:
            upgraded.append("|------|---------|---------|------|------------|------|------|")
        elif line.startswith("|"):
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if len(cells) >= 5:
                while len(cells) < 7:
                    cells.append("")
                upgraded.append("| " + " | ".join(cells[:7]) + " |")
            else:
                upgraded.append(line)
        else:
            upgraded.append(line)
    text = "\n".join(upgraded).rstrip() + "\n"
    if "| 编号 | 埋入章节 |" not in text:
        text = text.rstrip() + "\n\n" + default_foreshadow_table()
    return text


def apply_mock_env(enabled: bool) -> None:
    if enabled:
        os.environ["NOVEL_LLM_MODE"] = "mock"
        os.environ["NOVEL_RAG_MODE"] = "mock"


def build_context(rag: object, chapter_outline: str) -> str:
    """V1.3 起委托给 prompt_assembly.build_chapter_context，注入项目宪法/故事规格/文风/总纲。"""
    from prompt_assembly import build_chapter_context

    return build_chapter_context(PROJECT_DIR, rag, chapter_outline)


def run_full(chapter_num: int, mock: bool = False, skip_drama_diagnose: bool = False) -> None:
    apply_mock_env(mock)
    from dramatic_arc_diagnostics import build_character_briefs, diagnose_chapter_drama, write_diagnostics
    from literary_critic import analyze_literary_view, write_literary_view
    from llm_router import LLMRouter
    from prompt_assembly import (
        build_axis_context,
        build_chapter_context,
        render_prose_system_prompt,
        render_task_card_block,
    )
    from quality_diagnostics import (
        analyze_chapter_quality,
        quality_needs_revision,
        render_revision_brief,
        write_quality_diagnostics,
    )
    from rag_engine import NovelRAG
    from style_court import adjudicate, write_style_court
    from structured_store import read_task_card, sync_task_card_from_outline, write_review_json

    rag = NovelRAG(PROJECT_DIR)
    llm = LLMRouter(project_dir=PROJECT_DIR)
    ch = ch_str(chapter_num)

    chapter_outline = load(f"01_大纲/章纲/第{ch}章.md")
    world_settings = load("00_世界观/世界观.md")
    recent_summary = load("03_滚动记忆/最近摘要.md")

    if not chapter_outline.strip():
        print(f"[错误] 第{ch}章章纲不存在或为空，请先创建 01_大纲/章纲/第{ch}章.md")
        sys.exit(1)

    sync_task_card_from_outline(
        PROJECT_DIR,
        chapter_num,
        chapter_outline,
        llm=llm,
        context=build_axis_context(PROJECT_DIR),
    )
    task_card_path = PROJECT_DIR / "01_大纲" / "章纲" / f"第{ch}章_task_card.json"
    print(f"[结构化] 章节任务卡已保存 → {task_card_path.relative_to(PROJECT_DIR)}")
    task_card = read_task_card(PROJECT_DIR, chapter_num)
    if task_card and task_card.status != "confirmed":
        print("[提示] 章节任务卡尚未确认。CLI 继续执行；WebUI 正式写作会提示先确认任务卡。")

    system_prompt = render_prose_system_prompt(PROJECT_DIR, chapter_num)
    full_context = build_chapter_context(PROJECT_DIR, rag, chapter_outline)
    task_card_block = render_task_card_block(PROJECT_DIR, chapter_num)
    audit_reference = world_settings

    print(f"[1/6] 生成第{chapter_num}章草稿...")
    draft = llm.generate_chapter(
        system_prompt, full_context, chapter_outline, task_card_text=task_card_block
    )
    draft_path = save(f"02_正文/第{ch}章_草稿.md", draft)
    print(f"      草稿已保存 → {draft_path.relative_to(PROJECT_DIR)}（{word_count_zh(draft)}字）")

    print("[2/5] 逻辑审计...")
    audit_result = llm.audit_logic(draft, audit_reference, recent_summary)
    audit_path = save(f"04_审核日志/第{ch}章_审计.md", audit_result)
    review_json_path = write_review_json(PROJECT_DIR, chapter_num, audit_result, getattr(llm, "DEEPSEEK_MODEL", ""))
    print(f"      审计报告已保存 → {audit_path.relative_to(PROJECT_DIR)}")
    print(f"      审计 JSON 已保存 → {review_json_path.relative_to(PROJECT_DIR)}")

    print("[3/5] 读者镜像检查（参考层）...")
    reader_mirror = llm.reader_mirror(draft, recent_summary)
    mirror_path = save(f"04_审核日志/第{ch}章_读者镜像.md", reader_mirror)
    print(f"      读者镜像已保存 → {mirror_path.relative_to(PROJECT_DIR)}")

    final_draft = draft
    final_source_rel = f"02_正文/第{ch}章_草稿.md"
    draft_quality = analyze_chapter_quality(PROJECT_DIR, chapter_num, draft, final_source_rel)
    needs_audit_revision = has_actionable_audit_issue(audit_result)
    needs_quality_revision = quality_needs_revision(draft_quality)
    if needs_audit_revision or needs_quality_revision:
        reason = "审计发现问题" if needs_audit_revision else "质量诊断建议打磨"
        print(f"[4/5] {reason}，生成修订稿...")
        quality_brief = render_revision_brief(draft_quality)
        revision_prompt = (
            f"以下是逻辑审计发现的问题：\n\n{audit_result}\n\n"
            f"以下是读者视角反馈（参考层，不强制必改）：\n\n{reader_mirror}\n\n"
            f"以下是章节质量诊断给出的改稿指令：\n\n{quality_brief}\n\n"
            f"请修订以下章节，修正反馈中指出的问题，保持文风、既定剧情和任务卡目标不变。\n\n"
            f"【硬约束 · 保留质感】\n"
            f"- 原文中的留白、停顿、未说完的话、未解状态必须保留，不要为了'让段落完整'而补全，"
            f"不要为了'让信息更清楚'而展开解释。\n"
            f"- 不要为了过冲突信号、主动性、感官词等指标而强行加冲突词、动作或形容词。\n"
            f"- 改稿只动反馈中点名的局部，其他段落原样保留。\n\n"
            f"原文：\n\n{draft}"
        )
        final_draft = llm.revise_chapter(
            system_prompt, full_context, revision_prompt, task_card_text=task_card_block
        )
        revised_path = save(f"02_正文/第{ch}章_修订稿.md", final_draft)
        final_source_rel = f"02_正文/第{ch}章_修订稿.md"
        print(f"      修订稿已保存 → {revised_path.relative_to(PROJECT_DIR)}")
        print("      修订稿复审...")
        reaudit_result = llm.audit_logic(final_draft, audit_reference, recent_summary)
        reaudit_rel = f"04_审核日志/第{ch}章_复审.md"
        reaudit_path = save(reaudit_rel, reaudit_result)
        from structured_store import write_review_json_for_source

        reaudit_json_path = write_review_json_for_source(
            PROJECT_DIR,
            chapter_num,
            reaudit_result,
            getattr(llm, "DEEPSEEK_MODEL", ""),
            reaudit_rel,
            target_id=f"ch{ch}_reaudit",
        )
        print(f"      复审报告已保存 → {reaudit_path.relative_to(PROJECT_DIR)}")
        print(f"      复审 JSON 已保存 → {reaudit_json_path.relative_to(PROJECT_DIR)}")
    else:
        print("[4/5] 审计和质量诊断未发现明显问题，跳过自动修订")

    print("      章节质量诊断...")
    quality_md, quality_json, quality_report = write_quality_diagnostics(
        PROJECT_DIR,
        chapter_num,
        final_draft,
        final_source_rel,
    )
    print(
        f"      质量诊断已保存 → {quality_md.relative_to(PROJECT_DIR)} / "
        f"{quality_json.relative_to(PROJECT_DIR)}（{quality_report['score']}分，{quality_report['grade']}）"
    )

    diag = None
    chapter_mode = (task_card.chapter_mode or "").lower() if task_card else ""
    drama_protected_modes = {"interior", "atmosphere", "bridge"}
    drama_skipped_by_mode = chapter_mode in drama_protected_modes
    if skip_drama_diagnose:
        print("      已跳过戏剧诊断（--skip-drama-diagnose）")
    elif drama_skipped_by_mode:
        print(f"      跳过戏剧诊断（chapter_mode='{chapter_mode}'，保护氛围/留白模式不必量化戏剧张力）")
    else:
        print("      戏剧结构诊断...")
        diag = diagnose_chapter_drama(
            PROJECT_DIR,
            chapter_num,
            final_draft,
            task_card_json=task_card.model_dump_json(indent=2) if task_card else "",
            character_briefs=build_character_briefs(PROJECT_DIR, final_draft),
            llm=llm,
        )
        drama_md, drama_json = write_diagnostics(PROJECT_DIR, diag)
        print(
            f"      戏剧诊断已保存 → {drama_md.relative_to(PROJECT_DIR)} / "
            f"{drama_json.relative_to(PROJECT_DIR)}（总分 {diag.overall_drama_score}）"
        )

    print("      文学批评层...")
    literary_view = analyze_literary_view(
        PROJECT_DIR,
        chapter_num,
        final_draft,
        task_card_json=task_card.model_dump_json(indent=2) if task_card else "",
        llm=llm,
    )
    literary_md, literary_json = write_literary_view(PROJECT_DIR, literary_view)
    print(
        f"      文学批评已保存 → {literary_md.relative_to(PROJECT_DIR)} / "
        f"{literary_json.relative_to(PROJECT_DIR)}"
    )

    print("      风格法庭裁决...")
    court_decision = adjudicate(PROJECT_DIR, chapter_num, quality_report, literary_view, task_card=task_card)
    court_md, court_json = write_style_court(PROJECT_DIR, court_decision)
    print(
        f"      风格法庭已保存 → {court_md.relative_to(PROJECT_DIR)} / "
        f"{court_json.relative_to(PROJECT_DIR)}（confirmed {len(court_decision.confirmed_issues)} / contested {len(court_decision.contested_issues)}）"
    )

    # V4.0 Phase B: 角色声音诊断
    print("      角色声音诊断...")
    from voice_diagnostics import analyze_character_voices as _voice, write_voice_diagnostics as _write_voice
    _vf = _voice(PROJECT_DIR, chapter_num, final_draft)
    _voice_md, _voice_json = _write_voice(PROJECT_DIR, _vf)
    print(f"      声音诊断已保存 → {_voice_md.relative_to(PROJECT_DIR)} / {_voice_json.relative_to(PROJECT_DIR)}")

    # V4.0: 合成编辑备忘录
    print("      生成编辑备忘录...")
    from editor_memo import synthesize_memo as _synth, write_memo as _write_memo
    _memo = _synth(
        PROJECT_DIR, chapter_num, final_draft,
        audit_text=audit_result,
        reader_mirror_text=reader_mirror,
        quality_report=quality_report, drama_diag=diag,
        literary_view=literary_view, style_court_decision=court_decision,
        llm=llm,
    )
    _memo_md, _memo_json = _write_memo(PROJECT_DIR, _memo)
    print(f"      编辑备忘录已保存 → {_memo_md.relative_to(PROJECT_DIR)} / {_memo_json.relative_to(PROJECT_DIR)}")

    print("[5/5] 生成草稿摘要（不写入滚动记忆/RAG）...")
    summary = llm.summarize_local(final_draft)
    summary_md, summary_json = write_draft_summary(chapter_num, summary, final_source_rel)
    print(
        f"      草稿摘要已保存 → {summary_md.relative_to(PROJECT_DIR)} / "
        f"{summary_json.relative_to(PROJECT_DIR)}"
    )

    print("      等待人工定稿；长期记忆和 RAG 将在 --finalize --yes 时更新")

    print(f"\n{'=' * 55}")
    print(f"第{chapter_num}章流水线完成。")
    print(f"草稿：02_正文/第{ch}章_草稿.md")
    print(f"审计：04_审核日志/第{ch}章_审计.md")
    print("下一步：人工精修后运行 --finalize --yes 更新四项滚动记忆。")
    print(f"{'=' * 55}\n")


def has_actionable_audit_issue(audit_result: str) -> bool:
    if "未发现明显逻辑问题" in audit_result or "未发现明显问题" in audit_result:
        return False
    return any(kw in audit_result for kw in ["【问题位置】", "矛盾", "冲突", "错误", "占位符"])


def run_audit_only(chapter_num: int, mock: bool = False) -> None:
    apply_mock_env(mock)
    from llm_router import LLMRouter
    from structured_store import write_review_json

    llm = LLMRouter(project_dir=PROJECT_DIR)
    ch = ch_str(chapter_num)
    draft = (
        load(f"02_正文/第{ch}章_修订稿.md")
        or load(f"02_正文/第{ch}章_草稿.md")
        or load(f"02_正文/第{ch}章_定稿.md")
    )
    if not draft:
        print(f"[错误] 找不到第{ch}章的修订稿、草稿或定稿")
        sys.exit(1)

    settings_doc = load("00_世界观/世界观.md")
    result = llm.audit_logic(draft, settings_doc, load("03_滚动记忆/最近摘要.md"))
    save(f"04_审核日志/第{ch}章_审计.md", result)
    write_review_json(PROJECT_DIR, chapter_num, result, getattr(llm, "DEEPSEEK_MODEL", ""))
    print(result)


def run_quality_diagnose(chapter_num: int) -> None:
    from quality_diagnostics import write_quality_diagnostics

    ch = ch_str(chapter_num)
    for rel in [
        f"02_正文/第{ch}章_定稿.md",
        f"02_正文/第{ch}章_修订稿.md",
        f"02_正文/第{ch}章_草稿.md",
    ]:
        text = load(rel)
        if text.strip():
            md_path, json_path, report = write_quality_diagnostics(PROJECT_DIR, chapter_num, text, rel)
            print(
                f"[完成] 质量诊断已保存：{md_path.relative_to(PROJECT_DIR)} / "
                f"{json_path.relative_to(PROJECT_DIR)}（{report['score']}分，{report['grade']}）"
            )
            return
    print(f"[错误] 第{ch}章没有可诊断正文，请先生成草稿、修订稿或定稿。")
    sys.exit(1)


def run_dramatic_diagnose(chapter_num: int, mock: bool = False) -> None:
    from dramatic_arc_diagnostics import build_character_briefs, diagnose_chapter_drama, write_diagnostics
    from llm_router import LLMRouter
    from structured_store import read_task_card

    ch = ch_str(chapter_num)
    for rel, label in [
        (f"02_正文/第{ch}章_修订稿.md", "修订稿"),
        (f"02_正文/第{ch}章_草稿.md", "草稿"),
        (f"02_正文/第{ch}章_定稿.md", "定稿"),
    ]:
        if not (PROJECT_DIR / rel).exists():
            continue
        chapter_text = load(rel)
        if not chapter_text.strip():
            continue
        card = read_task_card(PROJECT_DIR, chapter_num)
        task_card_json = card.model_dump_json(indent=2) if card else ""
        llm = LLMRouter(mode="mock" if mock else None, project_dir=PROJECT_DIR)
        diag = diagnose_chapter_drama(
            PROJECT_DIR,
            chapter_num,
            chapter_text,
            task_card_json=task_card_json,
            character_briefs=build_character_briefs(PROJECT_DIR, chapter_text),
            llm=llm,
        )
        md_path, json_path = write_diagnostics(PROJECT_DIR, diag)
        print(f"[戏剧诊断] 来源：{label}（{rel}）")
        print(f"[戏剧诊断] 已保存：{md_path.relative_to(PROJECT_DIR)} / {json_path.relative_to(PROJECT_DIR)}")
        print(
            f"[戏剧诊断] 总分：{diag.overall_drama_score}，"
            f"压力/弧光/画面：{diag.pressure_curve_score}/{diag.character_arc_score}/{diag.cinematic_score}"
        )
        from sample_pool import populate_from_chapter
        added = populate_from_chapter(PROJECT_DIR, chapter_num, chapter_text, diag.cinematic_score, diag.is_mock)
        if added:
            print(f"[样本池] 从第{ch}章入池 {added} 条样本。")
        return
    print(f"[错误] 第{ch}章没有可诊断正文，请先生成草稿、修订稿或定稿。")
    sys.exit(1)


def run_literary_critic(chapter_num: int, mock: bool = False) -> None:
    from literary_critic import analyze_literary_view, write_literary_view
    from llm_router import LLMRouter
    from quality_diagnostics import analyze_chapter_quality
    from structured_store import read_task_card
    from style_court import adjudicate, write_style_court

    ch = ch_str(chapter_num)
    for rel, label in [
        (f"02_正文/第{ch}章_定稿.md", "定稿"),
        (f"02_正文/第{ch}章_修订稿.md", "修订稿"),
        (f"02_正文/第{ch}章_草稿.md", "草稿"),
    ]:
        if not (PROJECT_DIR / rel).exists():
            continue
        chapter_text = load(rel)
        if not chapter_text.strip():
            continue
        card = read_task_card(PROJECT_DIR, chapter_num)
        llm = LLMRouter(mode="mock" if mock else None, project_dir=PROJECT_DIR)
        view = analyze_literary_view(
            PROJECT_DIR,
            chapter_num,
            chapter_text,
            task_card_json=card.model_dump_json(indent=2) if card else "",
            llm=llm,
        )
        literary_md, literary_json = write_literary_view(PROJECT_DIR, view)
        quality_report = analyze_chapter_quality(PROJECT_DIR, chapter_num, chapter_text, rel)
        court = adjudicate(PROJECT_DIR, chapter_num, quality_report, view, task_card=card)
        court_md, court_json = write_style_court(PROJECT_DIR, court)
        print(f"[文学批评] 来源：{label}（{rel}）")
        print(f"[文学批评] 已保存：{literary_md.relative_to(PROJECT_DIR)} / {literary_json.relative_to(PROJECT_DIR)}")
        print(
            f"[风格法庭] 已保存：{court_md.relative_to(PROJECT_DIR)} / {court_json.relative_to(PROJECT_DIR)} "
            f"confirmed={len(court.confirmed_issues)} contested={len(court.contested_issues)}"
        )
        return
    print(f"[错误] 第{ch}章没有可文学批评正文，请先生成草稿、修订稿或定稿。")
    sys.exit(1)


def run_drama_trends_report() -> None:
    """V3.1 跨章节戏剧诊断趋势统计。"""
    from dramatic_arc_diagnostics import compute_drama_trends, write_trends

    trends = compute_drama_trends(PROJECT_DIR)
    if not trends.chapters:
        print("[戏剧趋势] 没有找到任何章节戏剧诊断 JSON，无法生成趋势。")
        return

    print("=== 跨章节戏剧诊断趋势 ===\n")
    print(f"{'章号':<6} {'压力':<6} {'弧光':<6} {'画面':<6} {'综合':<6} {'Mock':<6}")
    print("-" * 42)
    for s in trends.chapters:
        print(f"第{s.chapter_number:02d}章  "
              f"{s.pressure_curve_score:<6} {s.character_arc_score:<6} "
              f"{s.cinematic_score:<6} {s.overall_drama_score:<6} "
              f"{'是' if s.is_mock else '否':<6}")

    print(f"\n滚动均值 (窗口=3): {trends.rolling_avg_overall}")
    print(f"趋势方向: {trends.trend_direction}")
    print(f"三维度均值 — 压力: {trends.avg_pressure}  弧光: {trends.avg_arc}  画面: {trends.avg_cinematic}")

    path = write_trends(PROJECT_DIR, trends)
    print(f"\n趋势 JSON 已保存: {path.relative_to(PROJECT_DIR)}")


def run_revise_from_feedback(chapter_num: int, mock: bool = False) -> None:
    apply_mock_env(mock)
    from dramatic_arc_diagnostics import (
        build_character_briefs,
        diagnose_chapter_drama,
        read_diagnostics,
        write_diagnostics,
    )
    from literary_critic import analyze_literary_view, write_literary_view
    from llm_router import LLMRouter
    from prompt_assembly import build_chapter_context, render_prose_system_prompt, render_task_card_block
    from quality_diagnostics import analyze_chapter_quality, write_quality_diagnostics
    from rag_engine import NovelRAG
    from style_court import adjudicate, write_style_court
    from structured_store import read_task_card, write_review_json_for_source

    ch = ch_str(chapter_num)
    source_rel = choose_revision_source(ch)
    if not source_rel:
        print(f"[错误] 找不到第{ch}章可修订来源（定稿/修订稿/草稿）")
        sys.exit(1)

    source_text = load(source_rel)
    if not source_text.strip():
        print(f"[错误] 第{ch}章修订来源为空：{source_rel}")
        sys.exit(1)

    llm = LLMRouter(project_dir=PROJECT_DIR)
    rag = NovelRAG(PROJECT_DIR)
    chapter_outline = load(f"01_大纲/章纲/第{ch}章.md")
    system_prompt = render_prose_system_prompt(PROJECT_DIR, chapter_num)
    ctx = build_chapter_context(PROJECT_DIR, rag, chapter_outline)
    task_card_block = render_task_card_block(PROJECT_DIR, chapter_num)
    card = read_task_card(PROJECT_DIR, chapter_num)

    audit_text = load(f"04_审核日志/第{ch}章_审计.md")
    mirror_text = load(f"04_审核日志/第{ch}章_读者镜像.md")
    drama_protected_modes = {"interior", "atmosphere", "bridge"}
    chapter_mode_r = (card.chapter_mode or "").lower() if card else ""
    drama_diag = read_diagnostics(PROJECT_DIR, chapter_num)
    if drama_diag is None and chapter_mode_r not in drama_protected_modes:
        drama_diag = diagnose_chapter_drama(
            PROJECT_DIR,
            chapter_num,
            source_text,
            task_card_json=card.model_dump_json(indent=2) if card else "",
            character_briefs=build_character_briefs(PROJECT_DIR, source_text),
            llm=llm,
        )
        write_diagnostics(PROJECT_DIR, drama_diag)
        from sample_pool import populate_from_chapter
        added = populate_from_chapter(PROJECT_DIR, chapter_num, source_text, drama_diag.cinematic_score, drama_diag.is_mock)
        if added:
            print(f"[样本池] 从第{ch}章入池 {added} 条样本。")
        print(f"[戏剧诊断] 已补生成第{ch}章戏剧诊断，作为改稿最高优先级输入。")
    elif chapter_mode_r in drama_protected_modes:
        print(f"      跳过戏剧诊断（chapter_mode='{chapter_mode_r}'，保护氛围/留白模式）")
    quality_report = analyze_chapter_quality(PROJECT_DIR, chapter_num, source_text, source_rel)
    literary_view = analyze_literary_view(
        PROJECT_DIR,
        chapter_num,
        source_text,
        task_card_json=card.model_dump_json(indent=2) if card else "",
        llm=llm,
    )
    write_literary_view(PROJECT_DIR, literary_view)
    court_decision = adjudicate(PROJECT_DIR, chapter_num, quality_report, literary_view, task_card=card)
    write_style_court(PROJECT_DIR, court_decision)
    # V4.0: 使用编辑备忘录替代原始拼接
    from editor_memo import synthesize_memo as _synth, memo_to_revision_prompt as _memo_prompt, write_memo as _write_memo
    _memo = _synth(
        PROJECT_DIR, chapter_num, source_text,
        audit_text=audit_text,
        reader_mirror_text=mirror_text,
        quality_report=quality_report, drama_diag=drama_diag,
        literary_view=literary_view, style_court_decision=court_decision,
        llm=llm,
    )
    _write_memo(PROJECT_DIR, _memo)
    _memo_block = _memo_prompt(_memo)
    prompt = (
        "请根据以下编辑备忘录生成一版可直接进入人工精修的章节修订稿。\n"
        "要求：不改核心剧情，不新增冲突设定，不提前揭露 forbidden，优先解决 P0 问题。\n\n"
        f"{_memo_block}\n\n"
        f"## 原文\n{source_text}"
    )

    revised = llm.revise_chapter(system_prompt, ctx, prompt, task_card_text=task_card_block)
    revised_path = save(f"02_正文/第{ch}章_修订稿.md", revised)
    print(f"[完成] 诊断驱动修订稿已保存：{revised_path.relative_to(PROJECT_DIR)}（{word_count_zh(revised)}字）")

    settings_doc = load("00_世界观/世界观.md")
    reaudit_result = llm.audit_logic(revised, settings_doc, load("03_滚动记忆/最近摘要.md"))
    reaudit_rel = f"04_审核日志/第{ch}章_复审.md"
    save(reaudit_rel, reaudit_result)
    write_review_json_for_source(
        PROJECT_DIR,
        chapter_num,
        reaudit_result,
        getattr(llm, "DEEPSEEK_MODEL", ""),
        reaudit_rel,
        target_id=f"ch{ch}_feedback_reaudit",
    )
    quality_md, quality_json, report = write_quality_diagnostics(
        PROJECT_DIR,
        chapter_num,
        revised,
        f"02_正文/第{ch}章_修订稿.md",
    )
    print(
        f"[完成] 复审与质量诊断已保存：{reaudit_rel} / {quality_md.relative_to(PROJECT_DIR)} / "
        f"{quality_json.relative_to(PROJECT_DIR)}（{report['score']}分，{report['grade']}）"
    )


def run_finalize(chapter_num: int, yes: bool = False, mock: bool = False) -> None:
    apply_mock_env(mock)
    from llm_router import LLMRouter
    from rag_engine import NovelRAG
    from structured_store import update_character_states_with_llm, write_foreshadow_json, write_memory_json

    ch = ch_str(chapter_num)
    source_rel = choose_finalize_source(ch)
    if not source_rel:
        print(f"[错误] 找不到第{ch}章可定稿来源（定稿/修订稿/草稿）")
        sys.exit(1)

    if not yes:
        print("[错误] 定稿会写入 02_正文 并更新长期记忆。请显式添加 --yes。")
        sys.exit(2)

    source_text = load(source_rel)
    final_rel = f"02_正文/第{ch}章_定稿.md"
    final_path = save(final_rel, source_text)
    print(f"[定稿] 已保存 → {final_path.relative_to(PROJECT_DIR)}")

    llm = LLMRouter(project_dir=PROJECT_DIR)
    summary = llm.summarize_local(source_text)
    chapter_outline = load(f"01_大纲/章纲/第{ch}章.md")

    update_recent_summary(chapter_num, summary)
    update_global_summary(chapter_num, summary)
    update_foreshadow_table(chapter_num, chapter_outline)
    try:
        character_result = update_character_states_with_llm(
            PROJECT_DIR,
            chapter_num,
            source_text,
            summary,
            llm,
            chapter_outline,
        )
    except Exception as exc:
        print(f"[警告] LLM 人物状态抽取失败，使用文本 fallback：{exc}")
        update_character_state(chapter_num, summary)
        character_result = {"markdown": None, "json": None, "changes": {}}
    memory_json_path = write_memory_json(
        PROJECT_DIR,
        chapter_num,
        source_text,
        summary,
        chapter_outline,
        character_result["changes"],
    )
    foreshadow_json_path = write_foreshadow_json(PROJECT_DIR, load("03_滚动记忆/伏笔追踪.md"))

    rag = NovelRAG(PROJECT_DIR)
    rag.reindex_all()
    print("[定稿] 四项滚动记忆已更新：全局摘要、最近摘要、伏笔追踪、人物状态表")
    print(f"[结构化] 章节记忆 JSON 已保存 → {memory_json_path.relative_to(PROJECT_DIR)}")
    print(f"[结构化] 伏笔 JSON 已保存 → {foreshadow_json_path.relative_to(PROJECT_DIR)}")
    if character_result["changes"]:
        print(f"[结构化] 人物状态 JSON 已保存 → {character_result['json'].relative_to(PROJECT_DIR)}")


def choose_finalize_source(ch: str) -> str:
    for rel in [
        f"02_正文/第{ch}章_定稿.md",
        f"02_正文/第{ch}章_修订稿.md",
        f"02_正文/第{ch}章_草稿.md",
    ]:
        path = PROJECT_DIR / rel
        if path.exists() and path.read_text(encoding="utf-8").strip():
            return rel
    return ""


def choose_revision_source(ch: str) -> str:
    for rel in [
        f"02_正文/第{ch}章_定稿.md",
        f"02_正文/第{ch}章_修订稿.md",
        f"02_正文/第{ch}章_草稿.md",
    ]:
        if (PROJECT_DIR / rel).exists() and load(rel).strip():
            return rel
    return ""


def run_reindex(mock: bool = False) -> None:
    apply_mock_env(mock)
    from rag_engine import NovelRAG

    rag = NovelRAG(PROJECT_DIR)
    rag.reindex_all()


def run_init_volumes(count: int = 3) -> None:
    from long_structure import ensure_default_volumes

    paths = ensure_default_volumes(PROJECT_DIR, count=count)
    for path in paths:
        print(f"[V2.0] 卷纲已就绪：{path.relative_to(PROJECT_DIR)}")


def run_plan_card(chapter_num: int, confirm: bool = False, mock: bool = False) -> None:
    apply_mock_env(mock)
    from llm_router import LLMRouter
    from prompt_assembly import build_axis_context
    from structured_store import confirm_task_card, sync_task_card_from_outline

    ch = ch_str(chapter_num)
    outline = load(f"01_大纲/章纲/第{ch}章.md")
    if not outline.strip():
        print(f"[错误] 第{ch}章章纲不存在或为空")
        sys.exit(1)
    if confirm:
        card = confirm_task_card(PROJECT_DIR, chapter_num)
        print(f"[任务卡] 已确认第{chapter_num}章任务卡：{card.title}")
    else:
        llm = LLMRouter(project_dir=PROJECT_DIR)
        card = sync_task_card_from_outline(
            PROJECT_DIR,
            chapter_num,
            outline,
            preserve_confirmation=False,
            llm=llm,
            context=build_axis_context(PROJECT_DIR),
        )
        print(f"[任务卡] 已生成草稿：01_大纲/章纲/第{ch}章_task_card.json")
        print(f"[任务卡] 状态：{card.status}")


def run_plan_scenes(chapter_num: int, mock: bool = False) -> None:
    apply_mock_env(mock)
    from llm_router import LLMRouter
    from prompt_assembly import build_axis_context
    from structured_store import sync_scene_plan_from_task_card

    llm = LLMRouter(project_dir=PROJECT_DIR)
    scenes = sync_scene_plan_from_task_card(
        PROJECT_DIR,
        chapter_num,
        llm=llm,
        context=build_axis_context(PROJECT_DIR),
    )
    print(f"[场景] 已生成第{chapter_num}章场景计划，共 {len(scenes)} 个场景")
    print(f"[场景] 计划文件：01_大纲/章纲/第{chapter_num:03d}章_scenes/scene_plan.json")


def scene_output_dir(chapter_num: int) -> Path:
    return PROJECT_DIR / "02_正文" / f"第{chapter_num:03d}章_scenes"


def run_scene_draft(chapter_num: int, scene_number: int, mock: bool = False) -> None:
    apply_mock_env(mock)
    from llm_router import LLMRouter
    from rag_engine import NovelRAG
    from structured_store import next_scene_draft_version, read_scene_plan, update_scene_status

    scenes = read_scene_plan(PROJECT_DIR, chapter_num)
    scene = next((item for item in scenes if item.scene_number == scene_number), None)
    if scene is None:
        print("[错误] 找不到场景计划，请先运行 --plan-scenes")
        sys.exit(1)
    rag = NovelRAG(PROJECT_DIR)
    llm = LLMRouter(project_dir=PROJECT_DIR)
    from prompt_assembly import (
        build_chapter_context,
        render_prose_system_prompt,
        render_task_card_block,
    )

    system_prompt = render_prose_system_prompt(PROJECT_DIR, chapter_num)
    scene_prompt = (
        f"## 场景计划\n\n{scene.model_dump_json(indent=2)}\n\n"
        "请只写这个场景正文，不要输出解释，不要输出标题。"
    )
    context = build_chapter_context(PROJECT_DIR, rag, scene_prompt)
    task_card_block = render_task_card_block(PROJECT_DIR, chapter_num)
    draft = llm.generate_chapter(
        system_prompt, context, scene_prompt, task_card_text=task_card_block
    )
    out_dir = scene_output_dir(chapter_num)
    out_dir.mkdir(parents=True, exist_ok=True)
    version = next_scene_draft_version(PROJECT_DIR, chapter_num, scene_number)
    rel = f"02_正文/第{chapter_num:03d}章_scenes/scene_{scene_number:03d}_draft_v{version:03d}.md"
    save(rel, draft)
    update_scene_status(PROJECT_DIR, chapter_num, scene_number, "drafted", rel)
    print(f"[场景] 候选稿 v{version:03d} 已保存 → {rel}")


def choose_scene_draft_rel(chapter_num: int, scene_number: int) -> str:
    from structured_store import list_scene_drafts, read_scene_plan

    scenes = read_scene_plan(PROJECT_DIR, chapter_num)
    scene = next((item for item in scenes if item.scene_number == scene_number), None)
    if scene and scene.selected_draft_path and (PROJECT_DIR / scene.selected_draft_path).exists():
        return scene.selected_draft_path
    drafts = list_scene_drafts(PROJECT_DIR, chapter_num, scene_number)
    if drafts:
        return str(drafts[-1].relative_to(PROJECT_DIR)).replace("\\", "/")
    return ""


# ── V4.0 Phase D 场景级轻量诊断 ──────────────────────────────────────────────

BODY_ACTION_VERBS = re.compile(
    r"(走|跑|跳|推|拉|扯|拽|拍|打|敲|踢|踩|站|坐|躺|跪|爬|翻|转|扭|抓|握|捏|掐|按|压|抬|举|放|拿|递|接|扔|摔|砸|撕|扯|推|挡|抱|搂|扶|牵|挽|挥|摇|晃|点|指|划|写|画|擦|抹|扫|扔|丢|抛|投|射|刺|劈|砍|斩|割|划|戳|捅|弹|拨|拉|拽|拖|扛|背|挑|担|提|拎|挎|挽|抱|背|驮|抬|搬|移|挪|端|捧|托|举|挂|悬|吊|搭|架|支|撑|顶|抵|靠|倚|趴|俯|仰|低|抬|回|侧|转|扭|弯|躬|蹲|跃|蹦|跳|跨|迈|踏|踩|跺|踢|蹬|踹|踏|踩|行|走|跑|奔|冲|闯|钻|穿|插|挤|塞|填|装|卸|拆|开|关|合|闭|锁|扣|系|绑|捆|扎|缠|绕|卷|折|叠|摊|铺|展|收|藏|掖|塞|埋|挖|刨|掘|铲|填|堵|封|贴|粘|钉|拧|旋|扳|撬|别|卡|套|罩|盖|蒙|遮|挡|拦|阻|截|断|切|割|削|刮|剃|剪|裁|缝|补|织|编|绣|染|涂|刷|喷|洒|泼|浇|灌|倒|斟|舀|盛|装|填|塞|挤|压|榨|拧|绞|扭|掰|折|撕|扯|拉|拽|抽|拔|摘|采|捡|拾|取|拿|抓|握|捏|掐|捻|搓|揉|按|压|摩|抚|摸|拍|打|敲|击|叩|弹|拨|拂|拭|擦|揩|抹|涂|描|画|写|刻|雕|镂|凿|钻|钉|铆|焊|熔|铸|锻|炼|淬|浸|泡|渍|腌|熏|烤|烘|焙|煮|炖|焖|煨|煎|炸|炒|爆|熘|烩|蒸|烫|涮|熬|煲|烧)"
)

CONFLICT_PATTERNS = [
    re.compile(r"(要么|还是|或者|抉择|选择|取舍|难以|犹豫|彷徨|左右为难|进退两难)"),
    re.compile(r"(代价|后果|失去|输掉|承受|付出|赔上|葬送)"),
    re.compile(r"(拒绝|不[要会肯能该准许]|绝[不无]|断然|决不)"),
]

DIALOGUE_INFO_PATTERNS = [
    re.compile(r"[?？]"),
    re.compile(r"(告诉你|听我说|知道|发现|原来|真相|秘密|其实|竟然|居然|没想到|怎么回事)"),
    re.compile(r"(什么|谁|哪里|怎么|为什么|何时|多少|哪[个些]|干[吗嘛])"),
]


def _diagnose_scene_locally(
    chapter_num: int, scene_number: int, text: str
) -> dict:
    """纯规则场景轻量诊断：冲突可见性、动作密度、对白推进。"""
    notes: list[str] = []

    # 1) 冲突可见性
    conflict_hits = sum(len(p.findall(text)) for p in CONFLICT_PATTERNS)
    conflict_visible = conflict_hits >= 2
    if not conflict_visible:
        notes.append("冲突不可见 — 建议增加选择/代价/拒绝中的至少一种")

    # 2) 身体动作密度
    chars = len(text)
    action_count = len(BODY_ACTION_VERBS.findall(text))
    density = round(action_count / max(chars, 1) * 100, 2)
    if density < 1.5:
        notes.append(f"身体动作密度偏低 ({density}/百字) — 建议增加具体肢体动作")
    elif density > 8.0:
        notes.append(f"身体动作密度偏高 ({density}/百字) — 可能节奏过快，建议加入感官或心理停顿")

    # 3) 对白推进判定
    # 匹配中文引号内的对白内容
    _lq = chr(0x201C)  # "
    _rq = chr(0x201D)  # "
    dialogue_match = re.findall(rf"[“{_lq}「](.+?)[”{_rq}」\"]", text)
    if dialogue_match:
        dialogue_text = " ".join(dialogue_match)
        info_hits = sum(len(p.findall(dialogue_text)) for p in DIALOGUE_INFO_PATTERNS)
        dialogue_advances = info_hits >= 1
        if not dialogue_advances:
            notes.append("对白未推进信息 — 对话中缺少新信息、揭示或疑问")
    else:
        dialogue_advances = True  # 无对白场景不以此为扣分项

    # 综合评分 (0-10)
    score = 5
    if conflict_visible:
        score += 2
    if 1.5 <= density <= 8.0:
        score += 2
    elif density > 0:
        score += 1
    if dialogue_advances:
        score += 1
    if not notes:
        score += 1  # 无任何警告加满分

    return {
        "chapter_number": chapter_num,
        "scene_number": scene_number,
        "conflict_visible": conflict_visible,
        "body_action_density": density,
        "dialogue_advances": dialogue_advances,
        "notes": notes,
        "score": min(score, 10),
    }


def run_scene_review(chapter_num: int, scene_number: int, mock: bool = False) -> None:
    apply_mock_env(mock)
    from llm_router import LLMRouter
    from structured_store import update_scene_status, write_review_json_for_source

    llm = LLMRouter(project_dir=PROJECT_DIR)
    draft_rel = choose_scene_draft_rel(chapter_num, scene_number)
    draft = load(draft_rel)
    if not draft:
        print("[错误] 找不到场景草稿，请先运行 --draft-scene")
        sys.exit(1)
    settings_doc = load("00_世界观/世界观.md")
    review = llm.audit_logic(draft, settings_doc, load("03_滚动记忆/最近摘要.md"))
    review_rel = f"04_审核日志/第{chapter_num:03d}章_scene_{scene_number:03d}_review.md"
    save(review_rel, review)
    write_review_json_for_source(
        PROJECT_DIR,
        chapter_num,
        review,
        getattr(llm, "DEEPSEEK_MODEL", ""),
        review_rel,
        target_id=f"ch{chapter_num:03d}_scene_{scene_number:03d}",
    )
    update_scene_status(PROJECT_DIR, chapter_num, scene_number, "reviewed", draft_rel)
    print(f"[场景] 审稿已保存 → {review_rel}")

    # V4.0 Phase D: 场景级轻量诊断
    _diag = _diagnose_scene_locally(chapter_num, scene_number, draft)
    _diag_json_path = (
        PROJECT_DIR / "04_审核日志"
        / f"第{chapter_num:03d}章_scene_{scene_number:03d}_diagnostic.json"
    )
    from novel_schemas import SceneDiagnosticNote, write_json_model
    _diag_model = SceneDiagnosticNote(**_diag)
    write_json_model(_diag_json_path, _diag_model)
    # 回写到 ScenePlan
    from structured_store import read_scene_plan, write_scene_plan
    _plans = read_scene_plan(PROJECT_DIR, chapter_num)
    for _sp in _plans:
        if _sp.scene_number == scene_number:
            _sp.diagnostic_score = _diag["score"]
            _sp.diagnostic_notes = _diag["notes"]
            break
    write_scene_plan(PROJECT_DIR, chapter_num, _plans)
    print(f"[场景诊断] 冲突可见={_diag['conflict_visible']} "
          f"动作密度={_diag['body_action_density']:.1f}/百字 "
          f"对白推进={_diag['dialogue_advances']} "
          f"评分={_diag['score']}/10")


def run_compare_scene_drafts(chapter_num: int, scene_number: int) -> Path:
    from structured_store import list_scene_drafts, read_scene_plan

    drafts = list_scene_drafts(PROJECT_DIR, chapter_num, scene_number)
    if not drafts:
        print("[错误] 找不到场景候选稿，请先运行 --draft-scene")
        sys.exit(1)
    selected = ""
    for scene in read_scene_plan(PROJECT_DIR, chapter_num):
        if scene.scene_number == scene_number:
            selected = scene.selected_draft_path
            break

    lines = [
        f"# 第{chapter_num:03d}章 场景{scene_number:03d}候选稿对比",
        "",
        "| 版本 | 字数 | 状态 | 文件 | 开头预览 |",
        "|------|------|------|------|----------|",
    ]
    for draft_path in drafts:
        rel = str(draft_path.relative_to(PROJECT_DIR)).replace("\\", "/")
        text = draft_path.read_text(encoding="utf-8")
        version = re.search(r"_v(\d+)\.md$", draft_path.name)
        label = f"v{version.group(1)}" if version else draft_path.stem
        status = "已选择" if rel == selected else "候选"
        preview = first_line(text, 80).replace("|", "｜")
        lines.append(f"| {label} | {word_count_zh(text)} | {status} | `{rel}` | {preview} |")

    lines.extend(
        [
            "",
            "## 人工选择建议",
            "",
            "- 优先选择：人物动机清晰、冲突推进明确、与场景计划信息点贴合的版本。",
            "- 次要检查：是否出现未授权设定、占位符、时间线跳跃或过度解释。",
        ]
    )
    rel = f"04_审核日志/第{chapter_num:03d}章_scene_{scene_number:03d}_comparison.md"
    path = save(rel, "\n".join(lines) + "\n")
    print(f"[场景] 候选稿对比已保存 → {rel}")
    return path


def run_select_scene_draft(chapter_num: int, scene_number: int, version: int) -> None:
    from structured_store import select_scene_draft

    rel = f"02_正文/第{chapter_num:03d}章_scenes/scene_{scene_number:03d}_draft_v{version:03d}.md"
    select_scene_draft(PROJECT_DIR, chapter_num, scene_number, rel)
    print(f"[场景] 已选择候选稿 v{version:03d} → {rel}")


def run_assemble_scenes(chapter_num: int) -> None:
    from structured_store import read_scene_plan

    scenes = read_scene_plan(PROJECT_DIR, chapter_num)
    if not scenes:
        print("[错误] 找不到场景计划，请先运行 --plan-scenes")
        sys.exit(1)
    parts = []
    for scene in sorted(scenes, key=lambda item: item.scene_number):
        rel = scene.selected_draft_path or f"02_正文/第{chapter_num:03d}章_scenes/scene_{scene.scene_number:03d}_draft_v001.md"
        text = load(rel)
        if not text:
            print(f"[错误] 缺少场景正文：{rel}")
            sys.exit(1)
        parts.append(text.strip())
    chapter_text = "\n\n".join(parts).strip() + "\n"
    rel = f"02_正文/第{chapter_num:03d}章_草稿.md"
    save(rel, chapter_text)
    print(f"[场景] 已合并章节草稿 → {rel}")


def run_assist(kind: str, brief: str = "", chapter_num: int | None = None, character_name: str = "", mock: bool = False) -> None:
    from planning_assist import (
        generate_chapter_outline_draft,
        generate_character_draft,
        generate_outline_draft,
        generate_worldbuilding_draft,
    )

    if kind == "world":
        path = generate_worldbuilding_draft(PROJECT_DIR, brief, mock=mock)
    elif kind == "outline":
        path = generate_outline_draft(PROJECT_DIR, brief, mock=mock)
    elif kind == "character":
        path = generate_character_draft(PROJECT_DIR, character_name, brief, mock=mock)
    elif kind == "characters":
        from planning_assist import generate_character_batch_drafts
        paths = generate_character_batch_drafts(PROJECT_DIR, brief=brief, mock=mock)
        for item in paths:
            print(f"[辅助写作] 角色草案已保存 → {item.relative_to(PROJECT_DIR)}")
        return
    elif kind == "chapter":
        if chapter_num is None:
            raise SystemExit("--assist chapter 需要 --chapter")
        path = generate_chapter_outline_draft(PROJECT_DIR, chapter_num, brief, mock=mock)
    else:
        raise SystemExit("--assist 仅支持 world / outline / character / characters / chapter")
    print(f"[辅助写作] 草案已保存 → {path.relative_to(PROJECT_DIR)}")


def run_project_center(upgrade: bool = False, report_only: bool = False) -> None:
    from project_center import (
        generate_quality_report,
        run_v1_upgrade,
        write_project_status,
    )

    if upgrade:
        report = run_v1_upgrade(PROJECT_DIR)
        print("[V1.0] 项目中台已初始化并生成澄清问题、创作任务、质量报告。")
    elif report_only:
        generate_quality_report(PROJECT_DIR)
        report = write_project_status(PROJECT_DIR)
        print(f"[V1.0] 项目状态已更新 → {report.relative_to(PROJECT_DIR)}")
        return
    else:
        report = write_project_status(PROJECT_DIR)
        print(f"[V1.0] 项目状态已更新 → {report.relative_to(PROJECT_DIR)}")
        return
    print(f"[V1.0] 阻断项：{len(report.blockers)}")
    print(f"[V1.0] 风险项：{len(report.warnings)}")
    if report.next_actions:
        print(f"[V1.0] 下一步：{report.next_actions[0]}")


def run_delete_chapter(chapter_num: int, yes: bool = False, reason: str = "") -> None:
    if not yes:
        print("[错误] 删除章节会移动该章相关文件到 99_回收站。请显式添加 --yes。")
        sys.exit(2)
    from chapter_ops import delete_chapter_to_recycle
    from project_center import generate_quality_report

    result = delete_chapter_to_recycle(PROJECT_DIR, chapter_num, reason=reason)
    if not result["deleted"]:
        print(f"[删除] 未找到第{chapter_num:03d}章相关文件。")
        return
    generate_quality_report(PROJECT_DIR)
    print(f"[删除] 第{chapter_num:03d}章已移动到：{result['recycle_dir']}")
    print(f"[删除] 文件数量：{len(result['deleted'])}")


def run_project_snapshot(label: str = "") -> None:
    from project_archive import create_project_snapshot

    result = create_project_snapshot(PROJECT_DIR, label=label)
    print(f"[V1.1] 项目快照已生成 → {result.path.relative_to(PROJECT_DIR)}")
    print(f"[V1.1] 文件数：{result.file_count}，原始大小：{result.total_bytes} bytes")


def run_list_versions() -> None:
    from project_archive import collect_version_backups

    rows = collect_version_backups(PROJECT_DIR)
    if not rows:
        print("[V1.1] 暂无 versions/ 备份文件。")
        return
    print("| 备份文件 | 恢复目标 | 大小 | 修改时间 |")
    print("|----------|----------|------|----------|")
    for row in rows:
        print(f"| {row['rel_path']} | {row['target_rel_path']} | {row['size']} | {row['modified_at']} |")


def run_restore_version(version_rel_path: str, yes: bool = False) -> None:
    if not yes:
        print("[错误] 恢复备份会覆盖目标文件，并先备份当前文件。请显式添加 --yes。")
        sys.exit(2)
    from project_archive import restore_version_backup

    result = restore_version_backup(PROJECT_DIR, version_rel_path)
    print(f"[V1.1] 已恢复：{result['restored']}")
    print(f"[V1.1] 来源备份：{result['source']}")
    if result["current_backup"]:
        print(f"[V1.1] 当前文件已先备份：{result['current_backup']}")


def run_startup_package(
    inspiration: str,
    genre: str,
    length: str,
    pov: str,
    pace: str,
    mock: bool = False,
) -> None:
    from onboarding import generate_startup_package

    result = generate_startup_package(
        PROJECT_DIR,
        inspiration=inspiration,
        genre=genre,
        length=length,
        pov=pov,
        pace=pace,
        mock=mock,
    )
    print(f"[V1.5] 故事规格已写入 → {result['spec'].relative_to(PROJECT_DIR)}")
    for path in result["drafts"]:
        print(f"[V1.5] AI 草案已生成 → {path.relative_to(PROJECT_DIR)}")


def run_adopt_draft(draft_rel_path: str, target_rel_path: str = "", yes: bool = False) -> None:
    if not yes:
        print("[错误] 采纳草案会写入正式文件，并先备份当前文件。请显式添加 --yes。")
        sys.exit(2)
    from onboarding import adopt_ai_draft

    result = adopt_ai_draft(PROJECT_DIR, draft_rel_path, target_rel_path)
    print(f"[V1.5] 已采纳草案：{result.source.relative_to(PROJECT_DIR)}")
    print(f"[V1.5] 正式文件：{result.target.relative_to(PROJECT_DIR)}")
    if result.backup:
        print(f"[V1.5] 原正式文件已备份：{result.backup.relative_to(PROJECT_DIR)}")


def run_placeholder_help() -> None:
    from onboarding import placeholder_fix_suggestions

    rows = placeholder_fix_suggestions(PROJECT_DIR)
    if not rows:
        print("[V1.5] 未发现关键占位符。")
        return
    print("| 文件 | 行 | 占位内容 | 补全问题 | 建议 |")
    print("|------|----|----------|----------|------|")
    for row in rows[:50]:
        print(f"| {row['file']} | {row['line']} | {row['text']} | {row['question']} | {row['suggestion']} |")


def run_print_prompt(chapter_num: int) -> None:
    from prompt_assembly import build_chapter_context, render_prose_system_prompt, render_task_card_block

    ch = ch_str(chapter_num)
    chapter_outline = load(f"01_大纲/章纲/第{ch}章.md")
    system_prompt = render_prose_system_prompt(PROJECT_DIR, chapter_num)
    context = build_chapter_context(PROJECT_DIR, None, chapter_outline)
    task_card_block = render_task_card_block(PROJECT_DIR, chapter_num)
    print("===== SYSTEM PROMPT =====")
    print(system_prompt)
    print("===== USER CONTEXT =====")
    print(context)
    print("===== CHAPTER OUTLINE =====")
    print(chapter_outline)
    if task_card_block:
        print("===== TASK CARD =====")
        print(task_card_block)


def main() -> None:
    parser = argparse.ArgumentParser(description="AI 小说创作流水线")
    parser.add_argument("--chapter", type=int, help="要处理的章节号")
    parser.add_argument("--audit-only", action="store_true", help="仅审计，不生成")
    parser.add_argument("--quality-diagnose", action="store_true", help="V1.8 对当前稿运行章节质量诊断")
    parser.add_argument("--dramatic-diagnose", action="store_true", help="V2.7 对当前稿运行戏剧结构诊断")
    parser.add_argument("--literary-critic", action="store_true", help="V5.0-beta2 对当前稿运行文学批评层和风格法庭")
    parser.add_argument("--skip-drama-diagnose", action="store_true", help="V2.8 完整流水线中跳过戏剧诊断以节省 token")
    parser.add_argument("--revise-from-feedback", action="store_true", help="V1.9 根据审计、AI味和质量诊断生成修订稿并复查")
    parser.add_argument("--finalize", action="store_true", help="将当前稿件确认为定稿并更新四项滚动记忆")
    parser.add_argument("--yes", action="store_true", help="确认执行会写入长期记忆的操作")
    parser.add_argument("--reindex", action="store_true", help="重建全部 RAG 索引")
    parser.add_argument("--init-volumes", action="store_true", help="V2.0 初始化卷/幕结构模板到 01_大纲/卷纲")
    parser.add_argument("--volume-count", type=int, default=3, help="初始化卷纲数量，默认 3")
    parser.add_argument("--mock", action="store_true", help="使用 Mock LLM 和轻量 RAG 跑离线流程")
    parser.add_argument("--plan-card", action="store_true", help="从章纲生成章节任务卡 JSON")
    parser.add_argument("--confirm-card", action="store_true", help="确认章节任务卡")
    parser.add_argument("--plan-scenes", action="store_true", help="从任务卡生成场景计划")
    parser.add_argument("--scene", type=int, help="要处理的场景号")
    parser.add_argument("--draft-scene", action="store_true", help="生成单个场景草稿")
    parser.add_argument("--review-scene", action="store_true", help="审稿单个场景")
    parser.add_argument("--compare-scene", action="store_true", help="对比单个场景的全部候选稿")
    parser.add_argument("--select-draft", type=int, help="选择指定版本的场景候选稿，例如 2 表示 v002")
    parser.add_argument("--assemble-scenes", action="store_true", help="合并场景草稿为章节草稿")
    parser.add_argument("--assist", choices=["world", "outline", "character", "characters", "chapter"], help="生成前期策划草案")
    parser.add_argument("--brief", default="", help="辅助生成时的用户补充灵感")
    parser.add_argument("--character-name", default="", help="辅助生成角色档案时的角色名")
    parser.add_argument("--v1-upgrade", action="store_true", help="初始化/刷新 V1.0 项目中台")
    parser.add_argument("--project-report", action="store_true", help="生成项目级质量报告和状态 JSON")
    parser.add_argument("--drama-trends", action="store_true", help="V3.1 跨章节戏剧诊断趋势统计")
    parser.add_argument("--delete-chapter", action="store_true", help="删除指定章节相关文件到 99_回收站")
    parser.add_argument("--delete-reason", default="", help="删除章节时写入回收站清单的原因")
    parser.add_argument("--snapshot-project", action="store_true", help="生成 V1.1 项目快照 zip，不包含 .env、索引、日志和回收站")
    parser.add_argument("--snapshot-label", default="", help="项目快照文件名标签")
    parser.add_argument("--list-versions", action="store_true", help="列出全部 versions/ 自动备份")
    parser.add_argument("--restore-version", default="", help="恢复指定 versions/ 备份文件到原路径，需配合 --yes")
    parser.add_argument("--startup-package", action="store_true", help="V1.5 生成启动包：故事规格 + 世界观/总纲/角色/第一章草案")
    parser.add_argument("--genre", default="悬疑", help="启动包类型预设：玄幻/都市/悬疑/言情/科幻/历史")
    parser.add_argument("--length", default="30-80 万字", help="启动包篇幅预期")
    parser.add_argument("--pov", default="第三人称有限视角", help="启动包视角策略")
    parser.add_argument("--pace", default="中快节奏", help="启动包节奏偏好")
    parser.add_argument("--adopt-draft", default="", help="采纳 AI草案 到正式文件，需配合 --yes")
    parser.add_argument("--adopt-target", default="", help="采纳草案时指定正式目标路径")
    parser.add_argument("--placeholder-help", action="store_true", help="列出占位符补全问题和建议")
    parser.add_argument("--print-prompt", action="store_true", help="V2.6 打印当前章节的完整生成 prompt，用于验证风格样本注入")
    args = parser.parse_args()

    if args.startup_package:
        run_startup_package(args.brief, args.genre, args.length, args.pov, args.pace, mock=args.mock)
    elif args.adopt_draft:
        run_adopt_draft(args.adopt_draft, args.adopt_target, yes=args.yes)
    elif args.placeholder_help:
        run_placeholder_help()
    elif args.snapshot_project:
        run_project_snapshot(label=args.snapshot_label)
    elif args.list_versions:
        run_list_versions()
    elif args.restore_version:
        run_restore_version(args.restore_version, yes=args.yes)
    elif args.delete_chapter:
        if not args.chapter:
            parser.error("--delete-chapter 需要 --chapter")
        run_delete_chapter(args.chapter, yes=args.yes, reason=args.delete_reason)
    elif args.v1_upgrade:
        run_project_center(upgrade=True)
    elif args.project_report:
        run_project_center(report_only=True)
    elif args.drama_trends:
        run_drama_trends_report()
    elif args.reindex:
        run_reindex(mock=args.mock)
    elif args.init_volumes:
        run_init_volumes(count=args.volume_count)
    elif args.assist:
        run_assist(args.assist, brief=args.brief, chapter_num=args.chapter, character_name=args.character_name, mock=args.mock)
    elif args.chapter:
        if args.print_prompt:
            run_print_prompt(args.chapter)
        elif args.plan_card:
            run_plan_card(args.chapter, confirm=False, mock=args.mock)
        elif args.confirm_card:
            run_plan_card(args.chapter, confirm=True, mock=args.mock)
        elif args.plan_scenes:
            run_plan_scenes(args.chapter, mock=args.mock)
        elif args.draft_scene:
            if not args.scene:
                parser.error("--draft-scene 需要 --scene")
            run_scene_draft(args.chapter, args.scene, mock=args.mock)
        elif args.review_scene:
            if not args.scene:
                parser.error("--review-scene 需要 --scene")
            run_scene_review(args.chapter, args.scene, mock=args.mock)
        elif args.compare_scene:
            if not args.scene:
                parser.error("--compare-scene 需要 --scene")
            run_compare_scene_drafts(args.chapter, args.scene)
        elif args.select_draft is not None:
            if not args.scene:
                parser.error("--select-draft 需要 --scene")
            run_select_scene_draft(args.chapter, args.scene, args.select_draft)
        elif args.assemble_scenes:
            run_assemble_scenes(args.chapter)
        elif args.finalize:
            run_finalize(args.chapter, yes=args.yes, mock=args.mock)
        elif args.audit_only:
            run_audit_only(args.chapter, mock=args.mock)
        elif args.quality_diagnose:
            run_quality_diagnose(args.chapter)
        elif args.dramatic_diagnose:
            run_dramatic_diagnose(args.chapter, mock=args.mock)
        elif args.literary_critic:
            run_literary_critic(args.chapter, mock=args.mock)
        elif args.revise_from_feedback:
            run_revise_from_feedback(args.chapter, mock=args.mock)
        else:
            run_full(args.chapter, mock=args.mock, skip_drama_diagnose=args.skip_drama_diagnose)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
