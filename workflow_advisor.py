"""
Workflow recommendations for the WebUI.

This module is intentionally pure: it reads the file workspace and recommends
the next safe action, while WebUI/CLI decide whether to execute it.
"""

from __future__ import annotations

import json
import re
import hashlib
from pathlib import Path


ACTION_LABELS = {
    "generate_volume_outline": "生成当前卷纲",
    "review_volume_outline": "运行卷纲审查",
    "improve_volume_outline": "按审查改卷纲",
    "edit_outline": "补全章纲",
    "review_outline": "运行章纲审查",
    "improve_outline": "按审查改章纲",
    "generate_task_card": "生成任务卡",
    "confirm_task_card": "确认任务卡",
    "plan_scenes": "生成场景计划",
    "draft_scene": "生成缺失场景候选稿",
    "assemble_scenes": "合并场景草稿",
    "full_pipeline": "运行完整流水线",
    "audit": "运行逻辑审计",
    "reader_mirror": "运行读者镜像",
    "quality_diag": "运行章节质量诊断",
    "drama_diag": "运行戏剧结构诊断",
    "literary_critic": "运行文学批评",
    "style_court": "运行风格法庭裁决",
    "voice_diag": "运行角色声音诊断",
    "editor_memo": "生成编辑备忘录",
    "feedback_revise": "按反馈生成修订稿",
    "save_final": "保存为定稿草案",
    "finalize_memory": "定稿并更新记忆",
    "complete": "进入下一章",
}


ONBOARDING_STEPS: list[tuple[str, str, str]] = [
    ("spec", "故事规格", "今天 → 启动向导（一键生成全套）或 今天 → 规格文档（手动填写）"),
    ("world", "世界观", "今天 → 启动向导 或 笔记 → 世界观"),
    ("outline", "总纲", "今天 → 启动向导 或 全书 → 大纲 → 总纲"),
    ("characters", "主角档案", "今天 → 启动向导 或 笔记 → 世界观 → 角色档案"),
    ("chapters", "第一章章纲", "全书 → 大纲 → 章纲"),
]


def workspace_dashboard(project_dir: Path) -> dict:
    chapters = chapter_numbers(project_dir)
    chapter_cards = [chapter_flow(project_dir, num) for num in chapters]
    active = next((card for card in chapter_cards if card["recommendation"]["action"] != "complete"), None)
    project_status = _read_json(project_dir / "05_项目管理" / "project_status.json")
    return {
        "chapters": chapter_cards,
        "active_chapter": active["chapter_number"] if active else (chapters[-1] if chapters else None),
        "project": project_status,
        "onboarding": onboarding_state(project_dir),
        "totals": {
            "chapters": len(chapters),
            "complete": sum(1 for card in chapter_cards if card["recommendation"]["action"] == "complete"),
            "blocked": sum(1 for card in chapter_cards if card["recommendation"]["severity"] == "blocked"),
            "active": sum(1 for card in chapter_cards if card["recommendation"]["severity"] == "action"),
        },
    }


def onboarding_state(project_dir: Path) -> dict:
    """根据基础素材完成度推断当前所处的启动阶段，给新手指明下一步。"""
    spec_text = _read(project_dir / "05_项目管理" / "故事规格.md")
    world_text = _read(project_dir / "00_世界观" / "世界观.md")
    outline_text = _read(project_dir / "01_大纲" / "总纲.md")
    char_dir = project_dir / "00_世界观" / "角色档案"
    if char_dir.exists():
        char_files = [path for path in char_dir.glob("*.md") if path.name != "角色模板.md"]
    else:
        char_files = []
    chapters = chapter_numbers(project_dir)

    completed = {
        "spec": _has_real_content(spec_text, min_chars=200),
        "world": _has_real_content(world_text, min_chars=160),
        "outline": _has_real_content(outline_text, min_chars=160),
        "characters": len(char_files) >= 1,
        "chapters": bool(chapters),
    }

    stage_order = ["spec", "world", "outline", "characters", "chapters"]
    next_stage = next((key for key in stage_order if not completed[key]), None)
    if next_stage is None:
        stage = "writing"
    elif next_stage == "spec":
        stage = "spec"
    else:
        stage = next_stage

    next_step = {
        "spec": "建议先用「今天 → 启动向导」一键生成故事规格、世界观、总纲和角色草案，再人工调整；也可到「今天 → 规格文档」手动填写。",
        "world": "建议用「今天 → 启动向导」生成世界观草案后，到「笔记 → 世界观」精修。",
        "outline": "建议用「今天 → 启动向导」生成总纲草案后，到「全书 → 大纲 → 总纲」精修。",
        "characters": "建议用「今天 → 启动向导」生成角色草案后，到「笔记 → 世界观 → 角色档案」精修。",
        "chapters": "前往「全书 → 大纲 → 章纲」创建第一章章纲，AI 辅助可用。",
        "writing": "进入「今天」或「全书 → 写作」推进章节流水线。",
    }[stage]

    return {
        "stage": stage,
        "next_step": next_step,
        "next_stage_key": next_stage,
        "completed": completed,
        "progress": sum(1 for v in completed.values() if v),
        "total": len(completed),
        "steps": [
            {"key": key, "name": name, "location": loc, "done": completed[key]}
            for key, name, loc in ONBOARDING_STEPS
        ],
    }


_PLACEHOLDER_TOKENS = ("待补充", "在此填写", "请替换", "此处为空")


def _has_real_content(text: str, min_chars: int = 160) -> bool:
    if not text:
        return False
    if any(token in text for token in _PLACEHOLDER_TOKENS):
        return False
    cleaned = re.sub(r"\s+", "", text)
    return len(cleaned) >= min_chars


def chapter_flow(project_dir: Path, chapter_num: int) -> dict:
    ch = f"{chapter_num:03d}"
    outline_rel = f"01_大纲/章纲/第{ch}章.md"
    outline = _read(project_dir / outline_rel)
    placeholders = scan_outline_placeholders(project_dir, chapter_num)
    volume_state = _volume_state(project_dir, chapter_num)
    outline_review = _outline_review_state(project_dir, chapter_num, outline)
    task_card = _task_card(project_dir, chapter_num)
    scenes = _scene_plan(project_dir, chapter_num)
    scene_summary = _scene_summary(project_dir, chapter_num, scenes)
    has_draft = bool(_read(project_dir / "02_正文" / f"第{ch}章_草稿.md").strip())
    has_revised = bool(_read(project_dir / "02_正文" / f"第{ch}章_修订稿.md").strip())
    has_final = bool(_read(project_dir / "02_正文" / f"第{ch}章_定稿.md").strip())
    has_audit = bool(_read(project_dir / "04_审核日志" / f"第{ch}章_审计.md").strip())
    has_reader_mirror = bool(_read(project_dir / "04_审核日志" / f"第{ch}章_读者镜像.md").strip())
    has_quality_diag = bool(_read(project_dir / "04_审核日志" / f"第{ch}章_质量诊断.md").strip())
    has_drama_diag = bool(_read(project_dir / "04_审核日志" / f"第{ch}章_戏剧诊断.md").strip())
    has_literary = bool(_read(project_dir / "04_审核日志" / f"第{ch}章_文学批评.md").strip())
    has_style_court = bool(_read(project_dir / "04_审核日志" / f"第{ch}章_风格法庭.md").strip())
    has_voice_diag = bool(_read(project_dir / "04_审核日志" / f"第{ch}章_声音诊断.md").strip())
    has_editor_memo = bool(_read(project_dir / "04_审核日志" / f"第{ch}章_编辑备忘录.md").strip())
    quality_report = _read_json(project_dir / "04_审核日志" / f"第{ch}章_质量诊断.json")
    memory_updated = has_final and f"auto-chapter-{ch}" in _read(project_dir / "03_滚动记忆" / "全局摘要.md")
    recommendation = recommend_action(
        outline=outline,
        placeholders=placeholders,
        volume_state=volume_state,
        outline_review=outline_review,
        task_card=task_card,
        scenes=scenes,
        scene_summary=scene_summary,
        has_draft=has_draft,
        has_revised=has_revised,
        has_final=has_final,
        has_audit=has_audit,
        has_reader_mirror=has_reader_mirror,
        has_quality_diag=has_quality_diag,
        has_drama_diag=has_drama_diag,
        has_literary=has_literary,
        has_style_court=has_style_court,
        has_voice_diag=has_voice_diag,
        has_editor_memo=has_editor_memo,
        quality_report=quality_report,
        memory_updated=memory_updated,
    )
    return {
        "chapter_number": chapter_num,
        "title": _chapter_title(outline, chapter_num),
        "outline_path": outline_rel,
        "placeholders": placeholders,
        "outline_review": outline_review,
        "volume": volume_state,
        "task_card": task_card,
        "scenes": scene_summary,
        "artifacts": {
            "draft": has_draft,
            "volume_ready": (not volume_state.get("required", False)) or volume_state.get("ready", False),
            "volume_review": (not volume_state.get("required", False)) or volume_state.get("reviewed", False),
            "volume_improved": (not volume_state.get("required", False)) or volume_state.get("improved", False),
            "outline_review": outline_review.get("reviewed", False),
            "outline_improved": outline_review.get("improved", False),
            "revised": has_revised,
            "audit": has_audit,
            "reader_mirror": has_reader_mirror,
            "quality_diag": has_quality_diag,
            "drama_diag": has_drama_diag,
            "literary": has_literary,
            "style_court": has_style_court,
            "voice_diag": has_voice_diag,
            "editor_memo": has_editor_memo,
            "final": has_final,
            "memory_updated": memory_updated,
        },
        "steps": _steps(
            outline,
            placeholders,
            volume_state,
            outline_review,
            task_card,
            scene_summary,
            has_draft,
            has_audit,
            has_reader_mirror,
            has_quality_diag,
            has_drama_diag,
            has_literary,
            has_style_court,
            has_voice_diag,
            has_editor_memo,
            has_revised,
            has_final,
            memory_updated,
        ),
        "recommendation": recommendation,
    }


def recommend_action(
    *,
    outline: str,
    placeholders: list[dict],
    volume_state: dict,
    outline_review: dict,
    task_card: dict,
    scenes: list[dict],
    scene_summary: dict,
    has_draft: bool,
    has_revised: bool,
    has_final: bool,
    has_audit: bool,
    has_reader_mirror: bool,
    has_quality_diag: bool,
    has_drama_diag: bool = False,
    has_literary: bool = False,
    has_style_court: bool = False,
    has_voice_diag: bool = False,
    has_editor_memo: bool = False,
    quality_report: dict = None,
    memory_updated: bool = False,
) -> dict:
    if not outline.strip() or placeholders:
        return _recommend("edit_outline", "blocked", "章纲缺失或仍有占位符，先补完可执行信息。")
    if not task_card["exists"]:
        if volume_state.get("required", False) and not volume_state.get("ready", False):
            return _recommend(
                "generate_volume_outline",
                "action",
                "这是当前卷的第一章，先补齐卷纲，让后续章节承接本卷阶段任务。",
                volume_name=volume_state.get("volume_name", "第01卷.md"),
            )
        if volume_state.get("required", False) and not volume_state.get("reviewed", False):
            return _recommend(
                "review_volume_outline",
                "action",
                "这是当前卷的第一章，先审查卷纲的阶段目标、冲突升级、伏笔预算和卷末状态。",
                volume_name=volume_state.get("volume_name", "第01卷.md"),
            )
        if volume_state.get("required", False) and not volume_state.get("improved", False):
            return _recommend(
                "improve_volume_outline",
                "action",
                "根据卷纲审查意见自动改一版，本卷后续章节不再重复处理卷纲。",
                volume_name=volume_state.get("volume_name", "第01卷.md"),
            )
        if not outline_review.get("reviewed", False):
            return _recommend("review_outline", "action", "先审查章纲承接、冲突、伏笔和章末钩子，再拆任务卡。")
        if not outline_review.get("improved", False):
            return _recommend("improve_outline", "action", "根据章纲审查意见自动改一版，之后再进入任务卡。")
        return _recommend("generate_task_card", "action", "从章纲抽取结构化任务卡，后续生成会按任务卡校验。")
    if task_card["status"] != "confirmed":
        return _recommend("confirm_task_card", "action", "确认任务卡后再进入正式写作，避免模型按错误目标发散。")
    if not scenes:
        return _recommend("plan_scenes", "action", "把任务卡拆成场景计划，后续可逐场景生成候选稿。")
    if scene_summary["missing_drafts"]:
        target = scene_summary["missing_drafts"][0]
        return _recommend("draft_scene", "action", f"第 {target:03d} 场景还没有候选稿，先补齐场景草稿。", scene_number=target)
    if scenes and scene_summary["drafted"] == scene_summary["total"] and not has_draft:
        return _recommend("assemble_scenes", "action", "所有场景都有候选稿，可以合并为章节草稿。")
    if not has_draft:
        return _recommend("full_pipeline", "action", "没有草稿；可以直接运行完整流水线生成章节稿。")
    if not has_audit:
        return _recommend("audit", "action", "草稿已有，下一步做逻辑审计。")
    if not has_reader_mirror:
        return _recommend("reader_mirror", "action", "从目标读者视角检查追看欲、情感共振和类型卖点（参考层）。")
    if not has_quality_diag:
        return _recommend("quality_diag", "action", "补一份本地章节质量诊断，检查节奏、对白、套话和任务卡对齐。")
    # 戏剧诊断对推进型章节有用，但 interior / atmosphere / bridge 模式（保护氛围/留白）
    # 跑它会反向激励——和 style_court.PROTECTED_MODES 保持一致。
    chapter_mode = str(task_card.get("chapter_mode", "") or "").lower()
    drama_protected_modes = {"interior", "atmosphere", "bridge"}
    if not has_drama_diag and chapter_mode not in drama_protected_modes:
        return _recommend(
            "drama_diag",
            "action",
            "补充戏剧结构诊断（压力曲线 / 人物弧光 / 画面可视性）。"
            f"interior / atmosphere / bridge 模式会自动跳过；当前模式：{chapter_mode or 'plot'}。",
        )
    if not has_literary:
        return _recommend(
            "literary_critic",
            "action",
            "运行文学批评：观察可被记住的瞬间、未说之语、自我欺骗，保护工程诊断可能误伤的克制与氛围。",
        )
    if not has_style_court:
        return _recommend(
            "style_court",
            "action",
            "运行风格法庭：把工程指标与文学批评的冲突分流为必改与可争议，避免量化指标抹平人味。",
        )
    if not has_voice_diag:
        return _recommend("voice_diag", "action", "运行角色声音诊断：检查角色对白指纹是否区分得开。")
    if not has_editor_memo:
        return _recommend(
            "editor_memo",
            "action",
            "综合所有诊断生成编辑备忘录（P0/P1/P2 必改项 + 改稿约束）。",
        )
    if not has_revised and not has_final and _quality_report_needs_revision(quality_report):
        return _recommend(
            "feedback_revise",
            "action",
            "质量诊断显示存在硬伤（任务卡偏离 / forbidden 命中），按编辑备忘录生成修订稿。",
        )
    if not has_final and (has_revised or has_draft):
        return _recommend("save_final", "action", "把当前稿保存为定稿草案，然后在精修区人工打磨。")
    if has_final and not memory_updated:
        return _recommend("finalize_memory", "confirm", "定稿文件已存在，确认后更新滚动记忆和 RAG。")
    return _recommend("complete", "done", "本章闭环完成，可以切到下一章。")


def chapter_numbers(project_dir: Path) -> list[int]:
    chapter_dir = project_dir / "01_大纲" / "章纲"
    if not chapter_dir.exists():
        return []
    nums = []
    for path in chapter_dir.glob("第*章.md"):
        match = re.search(r"第(\d+)章", path.name)
        if match:
            nums.append(int(match.group(1)))
    return sorted(set(nums))


def scan_outline_placeholders(project_dir: Path, chapter_num: int) -> list[dict]:
    ch = f"{chapter_num:03d}"
    rel = f"01_大纲/章纲/第{ch}章.md"
    text = _read(project_dir / rel)
    # 占位符模式：必须是【...】包裹的特定词，或单独出现的占位词（排除掉带冒号的标签）
    patterns = re.compile(r"(?:主角名|章节标题|故事第X天|待补充|在此填写|请替换)(?!\s*[：:])")
    bracket_tokens = ["角色名", "章节标题", "主角名", "填写", "替换", "X", "Y"]
    findings = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        # 检查【...】形式
        bracket_hits = re.findall(r"【([^】]{0,40})】", line)
        has_bracket_placeholder = any(any(token in hit for token in bracket_tokens) for hit in bracket_hits)
        
        # 检查裸词形式，但排除掉章节标题等标签行（通过负向先行断言实现，或在此显式排除）
        if patterns.search(line) or has_bracket_placeholder:
            # 进一步排除：如果行内包含有效内容（冒号后有非占位符的实质字符），则不视为占位符
            placeholder_words = ["待补充", "在此填写", "请替换", "主角名", "章节标题", "故事第X天", "角色名"]
            if "：" in line or ":" in line:
                parts = re.split(r'[：:]', line, 1)
                if len(parts) > 1 and parts[1].strip() and not any(token in parts[1] for token in placeholder_words):
                    continue
            findings.append({"file": rel, "line": line_no, "text": line.strip()[:160]})
    return findings


def _recommend(action: str, severity: str, detail: str, **extra: object) -> dict:
    data = {
        "action": action,
        "label": ACTION_LABELS[action],
        "severity": severity,
        "detail": detail,
    }
    data.update(extra)
    return data


def _quality_report_needs_revision(report: dict) -> bool:
    # 直接复用 quality_diagnostics 的语义，避免本地副本和真源逻辑不一致。
    # 当前真源只在硬伤（forbidden / 任务卡核心未落地 / error 级）触发改稿，
    # 不再因总分低或品味问题（钩子偏弱、文气偏薄）自动改稿。
    if not report:
        return False
    try:
        from quality_diagnostics import quality_needs_revision
        return quality_needs_revision(report)
    except Exception:
        # 兜底：保留与真源等价的硬伤判断
        risky = {"触碰任务卡禁止事项", "任务卡对齐不足"}
        for item in report.get("findings", []):
            if item.get("item") in risky or item.get("level") == "error":
                return True
        alignment = report.get("task_card_alignment") or {}
        if alignment.get("forbidden_hits"):
            return True
        if any(check.get("covered") is False for check in alignment.get("checks") or []):
            return True
        return False


def _steps(
    outline: str,
    placeholders: list[dict],
    volume_state: dict,
    outline_review: dict,
    task_card: dict,
    scene_summary: dict,
    has_draft: bool,
    has_audit: bool,
    has_reader_mirror: bool,
    has_quality_diag: bool,
    has_drama_diag: bool,
    has_literary: bool,
    has_style_court: bool,
    has_voice_diag: bool,
    has_editor_memo: bool,
    has_revised: bool,
    has_final: bool,
    memory_updated: bool,
) -> list[dict]:
    # 与 recommend_action 保持一致：interior / atmosphere / bridge 模式跳过 drama_diag
    chapter_mode = str(task_card.get("chapter_mode", "") or "").lower()
    drama_required = chapter_mode not in {"interior", "atmosphere", "bridge"}
    return [
        {"name": "卷纲", "done": (not volume_state.get("required", False)) or bool(volume_state.get("ready"))},
        {
            "name": "卷纲审改",
            "done": (not volume_state.get("required", False))
            or (bool(volume_state.get("reviewed")) and bool(volume_state.get("improved"))),
        },
        {"name": "章纲", "done": bool(outline.strip()) and not placeholders},
        {"name": "章纲审改", "done": bool(outline_review.get("reviewed")) and bool(outline_review.get("improved"))},
        {"name": "任务卡", "done": task_card["status"] == "confirmed"},
        {"name": "场景", "done": scene_summary["total"] > 0 and scene_summary["drafted"] == scene_summary["total"]},
        {"name": "草稿", "done": has_draft},
        {"name": "审计", "done": has_audit},
        {"name": "读者镜像", "done": has_reader_mirror},
        {"name": "诊断", "done": has_quality_diag},
        # interior / atmosphere / bridge 模式保护留白不量化戏剧；其他模式须跑
        {"name": "戏剧", "done": (not drama_required) or has_drama_diag},
        {"name": "文学批评", "done": has_literary},
        {"name": "风格法庭", "done": has_style_court},
        {"name": "声音", "done": has_voice_diag},
        {"name": "编辑备忘录", "done": has_editor_memo},
        {"name": "修订", "done": has_revised or has_final},
        {"name": "定稿", "done": has_final},
        {"name": "记忆", "done": memory_updated},
    ]


def _task_card(project_dir: Path, chapter_num: int) -> dict:
    path = project_dir / "01_大纲" / "章纲" / f"第{chapter_num:03d}章_task_card.json"
    if not path.exists():
        return {"exists": False, "status": "missing"}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"exists": True, "status": "invalid"}
    return {
        "exists": True,
        "status": data.get("status", "draft"),
        "title": data.get("title", ""),
        "chapter_mode": data.get("chapter_mode", ""),
    }


def _outline_review_state(project_dir: Path, chapter_num: int, outline: str) -> dict:
    outline_hash = hashlib.sha256((outline or "").encode("utf-8")).hexdigest()
    review_path = project_dir / "AI审查缓存" / f"outline_outline_章纲_{chapter_num}.md"
    marker_path = project_dir / "AI审查缓存" / f"outline_outline_章纲_{chapter_num}_improved.json"
    marker = _read_json(marker_path)
    return {
        "reviewed": bool(_read(review_path).strip()),
        "improved": marker.get("outline_hash") == outline_hash,
        "outline_hash": outline_hash,
        "review_path": str(review_path.relative_to(project_dir)) if review_path.exists() else "",
        "marker_path": str(marker_path.relative_to(project_dir)) if marker_path.exists() else "",
    }


def _volume_state(project_dir: Path, chapter_num: int) -> dict:
    plan = _active_volume_plan(project_dir, chapter_num)
    if plan is None:
        fallback_number = max(1, ((chapter_num - 1) // 50) + 1)
        fallback_start = (fallback_number - 1) * 50 + 1
        volume_name = f"第{fallback_number:02d}卷.md"
        required = chapter_num == fallback_start
        return {
            "exists": False,
            "ready": False,
            "reviewed": False,
            "improved": False,
            "required": required,
            "start_chapter": fallback_start,
            "end_chapter": fallback_start + 49,
            "volume_name": volume_name,
            "path": f"01_大纲/卷纲/{volume_name}",
        }
    text = _read(plan["path"])
    volume_hash = hashlib.sha256((text or "").encode("utf-8")).hexdigest()
    volume_name = plan["path"].name
    start_chapter = plan.get("start") or ((int(plan.get("number", 1)) - 1) * 50 + 1)
    end_chapter = plan.get("end") or (start_chapter + 49)
    required = chapter_num == start_chapter
    generated_marker = _read_json(_volume_generated_marker_path(project_dir, volume_name))
    improved_marker = _read_json(_volume_improved_marker_path(project_dir, volume_name))
    reviewed = bool(_read(_review_cache_path(project_dir, "outline", f"outline_卷纲_{volume_name}")).strip())
    ready = bool(text.strip()) and (
        not _volume_needs_generation(text)
        or generated_marker.get("volume_hash") == volume_hash
        or improved_marker.get("volume_hash") == volume_hash
    )
    return {
        "exists": True,
        "ready": ready,
        "reviewed": reviewed,
        "improved": improved_marker.get("volume_hash") == volume_hash,
        "required": required,
        "start_chapter": start_chapter,
        "end_chapter": end_chapter,
        "volume_hash": volume_hash,
        "volume_name": volume_name,
        "path": str(plan["path"].relative_to(project_dir)),
        "review_path": str(_review_cache_path(project_dir, "outline", f"outline_卷纲_{volume_name}").relative_to(project_dir))
        if reviewed else "",
        "marker_path": str(_volume_improved_marker_path(project_dir, volume_name).relative_to(project_dir))
        if improved_marker else "",
    }


def _active_volume_plan(project_dir: Path, chapter_num: int) -> dict | None:
    volume_dir = project_dir / "01_大纲" / "卷纲"
    if not volume_dir.exists():
        return None
    fallback_number = max(1, ((chapter_num - 1) // 50) + 1)
    plans = []
    for path in sorted(volume_dir.glob("第*卷.md")):
        match = re.search(r"第(\d+)卷\.md$", path.name)
        if not match:
            continue
        text = _read(path)
        start, end = _extract_volume_chapter_range(text)
        plans.append({"number": int(match.group(1)), "path": path, "start": start, "end": end})
        if start is not None and end is not None and start <= chapter_num <= end:
            return plans[-1]
    for plan in plans:
        if plan["number"] == fallback_number:
            return plan
    return None


def _extract_volume_chapter_range(text: str) -> tuple[int | None, int | None]:
    match = re.search(r"(?:章节范围|覆盖章节|章节)[*]*\s*[：:][*]*\s*(?:第)?(\d{1,4})\s*(?:章)?\s*[-~—至到]\s*(?:第)?(\d{1,4})", text)
    if not match:
        return None, None
    start, end = int(match.group(1)), int(match.group(2))
    return min(start, end), max(start, end)


def _volume_needs_generation(text: str) -> bool:
    if not text.strip():
        return True
    if "待命名" in text:
        return True
    required = ("## 卷定位", "## 核心冲突", "## 角色弧线", "## 伏笔预算", "## 卷末状态")
    return not all(token in text for token in required)


def _review_cache_path(project_dir: Path, section: str, target: str) -> Path:
    safe = re.sub(r'[<>:"/\\|?*\s]+', "_", target).strip("_")
    return project_dir / "AI审查缓存" / f"{section}_{safe}.md"


def _volume_generated_marker_path(project_dir: Path, volume_name: str) -> Path:
    return project_dir / "AI审查缓存" / f"outline_outline_卷纲_{volume_name}_generated.json"


def _volume_improved_marker_path(project_dir: Path, volume_name: str) -> Path:
    return project_dir / "AI审查缓存" / f"outline_outline_卷纲_{volume_name}_improved.json"


def _scene_plan(project_dir: Path, chapter_num: int) -> list[dict]:
    path = project_dir / "01_大纲" / "章纲" / f"第{chapter_num:03d}章_scenes" / "scene_plan.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _scene_summary(project_dir: Path, chapter_num: int, scenes: list[dict]) -> dict:
    drafted = 0
    selected = 0
    missing = []
    scene_dir = project_dir / "02_正文" / f"第{chapter_num:03d}章_scenes"
    for scene in scenes:
        scene_num = int(scene.get("scene_number", 0))
        drafts = sorted(scene_dir.glob(f"scene_{scene_num:03d}_draft_v*.md")) if scene_dir.exists() else []
        if drafts:
            drafted += 1
        else:
            missing.append(scene_num)
        if scene.get("selected_draft_path"):
            selected += 1
    return {"total": len(scenes), "drafted": drafted, "selected": selected, "missing_drafts": missing}


def _chapter_title(outline: str, chapter_num: int) -> str:
    for line in outline.splitlines():
        if line.startswith("#"):
            return line.lstrip("#").strip()
    return f"第{chapter_num:03d}章"


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""
