"""
Project-level orchestration helpers for the V1.0 novel writing workbench.

The chapter pipeline remains file-first. This module adds the missing project
control layer: constitution, story spec, clarifications, task queue, quality
report, and a machine-readable status snapshot.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from novel_schemas import ProjectStatusReport, ProjectWorkflowStep, write_json_model
from novel_schemas import ProjectHealthSnapshot, ChapterHealthSnapshot
from templates import (
    SPEC_TEMPLATE,
    LEGACY_SPEC_TEMPLATES,
    CONSTITUTION_TEMPLATE,
    CLARIFY_TEMPLATE,
    TASKS_TEMPLATE,
    QUALITY_TEMPLATE,
)


CENTER_DIR = "05_项目管理"
CONSTITUTION = f"{CENTER_DIR}/创作宪法.md"
SPEC = f"{CENTER_DIR}/故事规格.md"
CLARIFY = f"{CENTER_DIR}/澄清问题.md"
TASKS = f"{CENTER_DIR}/创作任务.md"
QUALITY = f"{CENTER_DIR}/质量报告.md"
STATUS_JSON = f"{CENTER_DIR}/project_status.json"

PLACEHOLDER_PATTERNS = [
    r"\{在此[^}]*\}",
    r"在此填写",
    r"请替换",
    r"此处为空",
    r"主角名",
    r"章节标题",
    r"故事第X天",
    r"待补充",
    r"待命名",
]


def ensure_project_center(project_dir: Path) -> list[Path]:
    templates = {
        CONSTITUTION: CONSTITUTION_TEMPLATE,
        SPEC: SPEC_TEMPLATE,
        CLARIFY: CLARIFY_TEMPLATE,
        TASKS: TASKS_TEMPLATE,
        QUALITY: QUALITY_TEMPLATE,
    }
    created = []
    for rel, content in templates.items():
        path = project_dir / rel
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content.strip() + "\n", encoding="utf-8")
            created.append(path)
    if upgrade_legacy_spec(project_dir):
        created.append(project_dir / SPEC)
    return created


def upgrade_legacy_spec(project_dir: Path) -> bool:
    """如果故事规格仍是早期空白模板，升级为引导式模板，旧文件先备份。"""
    path = project_dir / SPEC
    if not path.exists():
        return False
    current = path.read_text(encoding="utf-8").strip()
    if current not in LEGACY_SPEC_TEMPLATES:
        return False
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    versions = path.parent / "versions"
    versions.mkdir(parents=True, exist_ok=True)
    backup = versions / f"{path.stem}_{timestamp}{path.suffix}"
    backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    path.write_text(SPEC_TEMPLATE.strip() + "\n", encoding="utf-8")
    return True


def build_project_status(project_dir: Path) -> ProjectStatusReport:
    ensure_project_center(project_dir)
    metrics = collect_metrics(project_dir)
    blockers = collect_blockers(project_dir, metrics)
    warnings = collect_warnings(project_dir, metrics)
    workflow = build_workflow(project_dir, metrics)
    next_actions = suggest_next_actions(workflow, blockers, warnings)
    drama_trends = None
    try:
        from dramatic_arc_diagnostics import compute_drama_trends
        trends = compute_drama_trends(project_dir)
        if trends.chapters:
            drama_trends = trends
    except Exception:
        pass

    return ProjectStatusReport(
        workflow=workflow,
        metrics=metrics,
        blockers=blockers,
        warnings=warnings,
        next_actions=next_actions,
        drama_trends=drama_trends,
    )


def compute_project_health(project_dir: Path) -> ProjectHealthSnapshot:
    """V5.0-rc1 计算项目级文学健康，返回三独立指标。

    工程稳健度：所有已诊断章的质量分均值（应用 writer overrides 后）。
    文学密度：每章可记忆瞬间数归一化到 0-100。
    风格一致度：角色对白相似度标志对数越少越接近 100。
    """
    audit_dir = project_dir / "04_审核日志"
    if not audit_dir.exists():
        return ProjectHealthSnapshot()

    chapter_nums: list[int] = []
    chapter_snapshots: list[ChapterHealthSnapshot] = []

    for qp in sorted(audit_dir.glob("第*章_质量诊断.json")):
        cn = _extract_chapter_num(qp.name)
        if cn is None:
            continue
        chapter_nums.append(cn)

        # 工程稳健度 —— 质量诊断分
        eng_score = 0.0
        try:
            qdata = json.loads(qp.read_text(encoding="utf-8"))
            raw = qdata.get("overall_score") or qdata.get("score") or 0
            eng_score = float(raw)
        except Exception:
            pass

        # 文学密度 —— 可记忆瞬间数
        memorable_count = 0
        lit_path = audit_dir / f"第{cn:03d}章_文学批评.json"
        if lit_path.exists():
            try:
                ldata = json.loads(lit_path.read_text(encoding="utf-8"))
                memorable_count = len(ldata.get("memorable_moments", []))
            except Exception:
                pass

        # 风格一致度 —— 对白相似度标志对数
        flagged_count = 0
        voice_path = audit_dir / f"第{cn:03d}章_声音诊断.json"
        if not voice_path.exists():
            voice_path = audit_dir / f"第{cn:03d}章_声音指纹.json"
        if voice_path.exists():
            try:
                vdata = json.loads(voice_path.read_text(encoding="utf-8"))
                flagged_count = len(vdata.get("flagged_pairs", []))
            except Exception:
                pass

        has_draft = (project_dir / "02_正文" / f"第{cn:03d}章_草稿.md").exists()

        # 归一化到 0-100
        literary_norm = min(100.0, (memorable_count / 5.0) * 100.0)
        style_norm = max(0.0, 100.0 - flagged_count * 20.0)

        chapter_snapshots.append(ChapterHealthSnapshot(
            chapter_number=cn,
            engineering_sturdiness=eng_score,
            literary_density=round(literary_norm, 1),
            style_consistency=round(style_norm, 1),
            has_draft=has_draft,
            memorable_moments_count=memorable_count,
            score_quality=int(eng_score) if eng_score else None,
        ))

    if not chapter_snapshots:
        return ProjectHealthSnapshot()

    # 总体均值
    avg_eng = round(sum(c.engineering_sturdiness for c in chapter_snapshots) / len(chapter_snapshots), 1)
    avg_lit = round(sum(c.literary_density for c in chapter_snapshots) / len(chapter_snapshots), 1)
    avg_style = round(sum(c.style_consistency for c in chapter_snapshots) / len(chapter_snapshots), 1)

    # 趋势（最近3章 vs 前3章）
    def _trend(snapshots: list[ChapterHealthSnapshot], attr: str) -> str:
        if len(snapshots) < 4:
            return "stable"
        recent = sum(getattr(c, attr) for c in snapshots[-3:]) / 3
        earlier = sum(getattr(c, attr) for c in snapshots[:-3][-3:]) / 3
        diff = recent - earlier
        if diff > 5:
            return "improving"
        elif diff < -5:
            return "declining"
        return "stable"

    # 弱章
    scored_eng = [c for c in chapter_snapshots if c.score_quality is not None]
    weakest_eng = min(scored_eng, key=lambda c: c.engineering_sturdiness).chapter_number if scored_eng else None
    weakest_lit = min(chapter_snapshots, key=lambda c: c.literary_density).chapter_number if chapter_snapshots else None
    most_drifted = min(chapter_snapshots, key=lambda c: c.style_consistency).chapter_number if chapter_snapshots else None

    total = len([n for n in chapter_nums if (project_dir / "02_正文" / f"第{n:03d}章_草稿.md").exists()])

    return ProjectHealthSnapshot(
        total_chapters_diagnosed=len(chapter_snapshots),
        total_chapters=max(total, len(chapter_snapshots)),
        engineering_sturdiness=avg_eng,
        literary_density=avg_lit,
        style_consistency=avg_style,
        engineering_trend=_trend(chapter_snapshots, "engineering_sturdiness"),
        literary_trend=_trend(chapter_snapshots, "literary_density"),
        style_trend=_trend(chapter_snapshots, "style_consistency"),
        chapter_snapshots=chapter_snapshots,
        weakest_chapter_engineering=weakest_eng,
        weakest_chapter_literary=weakest_lit,
        most_style_drifted_chapter=most_drifted,
    )


def _extract_chapter_num(filename: str) -> int | None:
    m = re.search(r"第(\d+)章", filename)
    return int(m.group(1)) if m else None


def write_project_status(project_dir: Path) -> Path:
    report = build_project_status(project_dir)
    return write_json_model(project_dir / STATUS_JSON, report)


def run_v1_upgrade(project_dir: Path) -> ProjectStatusReport:
    ensure_project_center(project_dir)
    generate_clarification_questions(project_dir)
    generate_writing_tasks(project_dir)
    generate_quality_report(project_dir)
    write_project_status(project_dir)
    return build_project_status(project_dir)


def collect_metrics(project_dir: Path) -> dict[str, int]:
    chapter_dir = project_dir / "01_大纲" / "章纲"
    volume_dir = project_dir / "01_大纲" / "卷纲"
    body_dir = project_dir / "02_正文"
    character_dir = project_dir / "00_世界观" / "角色档案"
    outlines = sorted(chapter_dir.glob("第*章.md")) if chapter_dir.exists() else []
    volumes = sorted(volume_dir.glob("第*卷.md")) if volume_dir.exists() else []
    task_cards = sorted(chapter_dir.glob("*_task_card.json")) if chapter_dir.exists() else []
    scene_plans = sorted(chapter_dir.glob("第*章_scenes/scene_plan.json")) if chapter_dir.exists() else []
    drafts = sorted(body_dir.glob("第*章_草稿.md")) if body_dir.exists() else []
    revisions = sorted(body_dir.glob("第*章_修订稿.md")) if body_dir.exists() else []
    finals = sorted(body_dir.glob("第*章_定稿.md")) if body_dir.exists() else []
    audits = sorted((project_dir / "04_审核日志").glob("第*章_审计.md")) if (project_dir / "04_审核日志").exists() else []
    drama_diagnostics = sorted((project_dir / "04_审核日志").glob("第*章_戏剧诊断.json")) if (project_dir / "04_审核日志").exists() else []
    manuscript_chapters = {
        num for num in (parse_chapter_num(path.name) for path in [*drafts, *revisions, *finals]) if num is not None
    }
    drama_chapters = {
        num for num in (parse_chapter_num(path.name) for path in drama_diagnostics) if num is not None
    }
    confirmed = sum(1 for path in task_cards if _task_card_status(path) == "confirmed")
    placeholders = scan_placeholders(project_dir)
    pending_foreshadows = _count_table_rows(project_dir / "03_滚动记忆" / "伏笔追踪.md", "待回收")
    characters = [
        path for path in character_dir.glob("*.md")
        if character_dir.exists() and path.name != "角色模板.md"
    ]
    return {
        "characters": len(characters),
        "volume_plans": len(volumes),
        "chapter_outlines": len(outlines),
        "task_cards": len(task_cards),
        "confirmed_task_cards": confirmed,
        "scene_plans": len(scene_plans),
        "drafts": len(drafts),
        "finals": len(finals),
        "audits": len(audits),
        "drama_diagnostics": len(drama_diagnostics),
        "manuscript_chapters": len(manuscript_chapters),
        "drama_diagnosed_chapters": len(drama_chapters),
        "placeholders": len(placeholders),
        "pending_foreshadows": pending_foreshadows,
    }


def build_workflow(project_dir: Path, metrics: dict[str, int]) -> list[ProjectWorkflowStep]:
    return [
        _step(project_dir, "constitution", "创作宪法", CONSTITUTION),
        _step(project_dir, "specify", "故事规格", SPEC),
        ProjectWorkflowStep(
            key="clarify",
            name="澄清问题",
            status=_table_status(project_dir / CLARIFY),
            detail="关键问题已收束" if _table_status(project_dir / CLARIFY) == "ready" else "仍有待回答问题",
            source_path=CLARIFY,
        ),
        ProjectWorkflowStep(
            key="plan",
            name="长篇计划",
            status="ready" if metrics["chapter_outlines"] and metrics["volume_plans"] else "missing",
            detail=f"{metrics['volume_plans']} 份卷纲，{metrics['chapter_outlines']} 份章纲，{metrics['scene_plans']} 份场景计划",
            source_path="01_大纲",
        ),
        ProjectWorkflowStep(
            key="tasks",
            name="创作任务",
            status=_table_status(project_dir / TASKS),
            detail="任务队列已生成" if (project_dir / TASKS).exists() else "任务队列未生成",
            source_path=TASKS,
        ),
        ProjectWorkflowStep(
            key="write",
            name="章节写作",
            status=_writing_status(metrics),
            detail=f"{metrics['drafts']} 草稿 / {metrics['finals']} 定稿",
            source_path="02_正文",
        ),
        ProjectWorkflowStep(
            key="analyze",
            name="质量分析",
            status="ready" if (project_dir / QUALITY).exists() and "尚未生成" not in _read(project_dir / QUALITY) else "missing",
            detail=f"{metrics['audits']} 份章节审计，{metrics['drama_diagnostics']} 份戏剧诊断，{metrics['placeholders']} 处占位符",
            source_path=QUALITY,
        ),
    ]


def generate_clarification_questions(project_dir: Path) -> Path:
    ensure_project_center(project_dir)
    spec = _read(project_dir / SPEC)
    world = _read(project_dir / "00_世界观" / "世界观.md")
    outline = _read(project_dir / "01_大纲" / "总纲.md")
    questions = []
    if "待补充" in spec or len(_meaningful_text(spec)) < 80:
        questions.append("故事的一句话卖点和目标读者是否已经明确到可指导章节取舍？")
    if len(_meaningful_text(world)) < 120:
        questions.append("世界运行规则、力量边界或社会结构是否足够支撑长篇冲突？")
    volume_dir = project_dir / "01_大纲" / "卷纲"
    volume_count = len(list(volume_dir.glob("第*卷.md"))) if volume_dir.exists() else 0
    if len(_meaningful_text(outline)) < 120:
        questions.append("总纲是否已经包含阶段目标、主要反转和结局方向？")
    if not volume_count:
        questions.append("是否需要先按卷/幕划分长篇结构，明确每卷主冲突、转折和伏笔预算？")
    if not list((project_dir / "00_世界观" / "角色档案").glob("*.md")):
        questions.append("主角、反派和核心配角的动机与缺陷是否已经建档？")
    if not questions:
        questions.append("下一阶段最需要优先打磨的是人物弧线、伏笔回收还是章节节奏？")

    lines = [
        "# 澄清问题",
        "",
        "| 编号 | 问题 | 状态 | 决策 |",
        "|------|------|------|------|",
    ]
    for idx, question in enumerate(questions[:5], start=1):
        lines.append(f"| Q{idx:03d} | {question} | 待回答 |  |")
    path = project_dir / CLARIFY
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def generate_writing_tasks(project_dir: Path) -> Path:
    ensure_project_center(project_dir)
    rows = []
    if scan_placeholders(project_dir):
        rows.append(("T001", "高", "待办", "清理世界观、总纲、卷纲、章纲中的占位符", "无"))
    if _contains_placeholder(_read(project_dir / SPEC)):
        rows.append(("T002", "高", "待办", "完善故事规格，明确目标读者、核心冲突和成功标准", "无"))
    volume_dir = project_dir / "01_大纲" / "卷纲"
    volume_plans = list(volume_dir.glob("第*卷.md")) if volume_dir.exists() else []
    if not volume_plans:
        rows.append(("T003", "高", "待办", "初始化并完善卷/幕结构，避免长篇中段漂移", "总纲"))

    chapter_dir = project_dir / "01_大纲" / "章纲"
    outlines = sorted(chapter_dir.glob("第*章.md")) if chapter_dir.exists() else []
    next_id = 10
    for outline in outlines:
        chapter_num = parse_chapter_num(outline.name)
        if chapter_num is None:
            continue
        ch = f"{chapter_num:03d}"
        if not (chapter_dir / f"第{ch}章_task_card.json").exists():
            rows.append((f"T{next_id:03d}", "高", "待办", f"生成并确认第{ch}章任务卡", f"第{ch}章章纲"))
            next_id += 1
        if not (project_dir / "02_正文" / f"第{ch}章_草稿.md").exists():
            rows.append((f"T{next_id:03d}", "中", "待办", f"生成第{ch}章草稿或场景候选稿", f"第{ch}章任务卡"))
            next_id += 1
        if (project_dir / "02_正文" / f"第{ch}章_草稿.md").exists() and not (project_dir / "04_审核日志" / f"第{ch}章_审计.md").exists():
            rows.append((f"T{next_id:03d}", "中", "待办", f"运行第{ch}章逻辑审计", f"第{ch}章草稿"))
            next_id += 1
        if (project_dir / "02_正文" / f"第{ch}章_定稿.md").exists() and f"auto-chapter-{ch}" not in _read(project_dir / "03_滚动记忆" / "全局摘要.md"):
            rows.append((f"T{next_id:03d}", "高", "待办", f"更新第{ch}章定稿记忆", f"第{ch}章定稿"))
            next_id += 1

    if not rows:
        rows.append(("T001", "中", "进行中", "继续下一章：章纲 -> 任务卡 -> 场景候选稿 -> 审计 -> 定稿记忆", "当前项目状态"))

    lines = ["# 创作任务", "", "| 编号 | 优先级 | 状态 | 任务 | 依赖 |", "|------|--------|------|------|------|"]
    lines.extend(f"| {task_id} | {priority} | {status} | {task} | {dependency} |" for task_id, priority, status, task, dependency in rows)
    path = project_dir / TASKS
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def generate_quality_report(project_dir: Path) -> Path:
    ensure_project_center(project_dir)
    metrics = collect_metrics(project_dir)
    placeholders = scan_placeholders(project_dir)
    blockers = collect_blockers(project_dir, metrics)
    warnings = collect_warnings(project_dir, metrics)
    lines = [
        "# 质量报告",
        "",
        "## 总览",
        f"- 角色：{metrics['characters']}",
        f"- 卷纲：{metrics['volume_plans']}",
        f"- 章纲：{metrics['chapter_outlines']}",
        f"- 任务卡：{metrics['confirmed_task_cards']}/{metrics['task_cards']} 已确认",
        f"- 草稿/定稿：{metrics['drafts']}/{metrics['finals']}",
        f"- 待回收伏笔：{metrics['pending_foreshadows']}",
    ]

    # V3.1 戏剧趋势
    lines.extend(["", "## 跨章节戏剧趋势"])
    try:
        from dramatic_arc_diagnostics import compute_drama_trends
        trends = compute_drama_trends(project_dir)
        if trends.chapters:
            lines.append(f"- 趋势方向: {trends.trend_direction}")
            lines.append(f"- 三维度均值 — 压力: {trends.avg_pressure}  弧光: {trends.avg_arc}  画面: {trends.avg_cinematic}")
            lines.append(f"- 滚动均值: {trends.rolling_avg_overall}")
            lines.append("")
            lines.append("| 章号 | 压力 | 弧光 | 画面 | 综合 | Mock |")
            lines.append("|---|---:|---:|---:|---:|")
            for s in trends.chapters:
                lines.append(f"| 第{s.chapter_number:02d}章 | {s.pressure_curve_score} | {s.character_arc_score} | {s.cinematic_score} | {s.overall_drama_score} | {'是' if s.is_mock else '否'} |")
        else:
            lines.append("- 暂无戏剧诊断数据")
    except Exception:
        lines.append("- 趋势计算失败，请检查日志")

    lines.extend(["", "## 阻断项"])
    lines.extend([f"- {item}" for item in blockers] or ["- 无"])
    lines.extend(["", "## 风险项"])
    lines.extend([f"- {item}" for item in warnings] or ["- 无"])
    lines.extend(["", "## 占位符"])
    if placeholders:
        lines.extend(f"- `{item['file']}:{item['line']}` {item['text']}" for item in placeholders[:50])
    else:
        lines.append("- 未发现关键占位符")
    lines.extend(["", "## 下一步", *[f"- {item}" for item in suggest_next_actions(build_workflow(project_dir, metrics), blockers, warnings)]])
    path = project_dir / QUALITY
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_project_status(project_dir)
    return path


def scan_placeholders(project_dir: Path, paths: list[str] | None = None) -> list[dict[str, object]]:
    if paths is None:
        paths = [
            "00_世界观/世界观.md",
            "00_世界观/文风档案.md",
            "01_大纲/总纲.md",
            "03_滚动记忆/伏笔追踪.md",
            "03_滚动记忆/人物状态表.md",
        ]
        char_dir = project_dir / "00_世界观" / "角色档案"
        if char_dir.exists():
            paths.extend(str(path.relative_to(project_dir)).replace("\\", "/") for path in char_dir.glob("*.md") if path.name != "角色模板.md")
        volume_dir = project_dir / "01_大纲" / "卷纲"
        if volume_dir.exists():
            paths.extend(str(path.relative_to(project_dir)).replace("\\", "/") for path in volume_dir.glob("第*卷.md"))
        chapter_dir = project_dir / "01_大纲" / "章纲"
        if chapter_dir.exists():
            paths.extend(str(path.relative_to(project_dir)).replace("\\", "/") for path in chapter_dir.glob("第*章.md"))
    findings = []
    combined = re.compile("|".join(f"({pattern})" for pattern in PLACEHOLDER_PATTERNS))
    for rel in paths:
        text = _read(project_dir / rel)
        if not text:
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            if combined.search(line):
                findings.append({"file": rel, "line": line_no, "text": line.strip()[:160]})
    return findings


def collect_blockers(project_dir: Path, metrics: dict[str, int]) -> list[str]:
    blockers = []
    required = [
        "00_世界观/世界观.md",
        "00_世界观/文风档案.md",
        "01_大纲/总纲.md",
        "01_大纲/卷纲",
        "01_大纲/章纲",
        "02_正文",
        "03_滚动记忆/全局摘要.md",
        "03_滚动记忆/最近摘要.md",
        "prompts/正文生成.md",
    ]
    missing = [rel for rel in required if not (project_dir / rel).exists()]
    if missing:
        blockers.append("缺少核心目录或模板：" + "、".join(missing))
    if metrics["placeholders"]:
        blockers.append(f"仍有 {metrics['placeholders']} 处占位符，正式生成前需要处理")
    if not metrics["chapter_outlines"]:
        blockers.append("尚无章纲，无法进入章节流水线")
    if not metrics["volume_plans"]:
        blockers.append("尚无卷纲，长篇结构约束不会进入章节生成")
    return blockers


def collect_warnings(project_dir: Path, metrics: dict[str, int]) -> list[str]:
    warnings = []
    if metrics["task_cards"] and metrics["confirmed_task_cards"] < metrics["task_cards"]:
        warnings.append(f"{metrics['task_cards'] - metrics['confirmed_task_cards']} 张任务卡尚未确认")
    if metrics["drafts"] > metrics["audits"]:
        warnings.append("存在草稿数量多于审计报告的情况，建议补审")
    if metrics["manuscript_chapters"] > metrics["drama_diagnosed_chapters"]:
        warnings.append("存在正文稿件缺少戏剧诊断，建议运行 --dramatic-diagnose 或完整流水线")
    if metrics["pending_foreshadows"] > 20:
        warnings.append("待回收伏笔较多，建议按卷或每 10 章清点")
    if _contains_placeholder(_read(project_dir / SPEC)):
        warnings.append("故事规格仍有待补项，项目方向可能不够稳定")
    if metrics["chapter_outlines"] > 20 and metrics["volume_plans"] < 2:
        warnings.append("章纲数量已进入长篇规模，但卷/幕结构偏少，建议补卷纲")
    warnings.extend(collect_story_consistency_warnings(project_dir))
    return warnings


def collect_story_consistency_warnings(project_dir: Path) -> list[str]:
    """检查项目轴里的语义联动是否已经落地到正式文件。"""
    linkage_issues = collect_linkage_drift_issues(project_dir)
    warnings = [str(issue["message"]) for issue in linkage_issues]

    char_dir = project_dir / "00_世界观" / "角色档案"
    if not char_dir.exists():
        return warnings
    official_names = {
        path.stem
        for path in char_dir.glob("*.md")
        if path.name != "角色模板.md" and "AI草案" not in path.parts
    }
    if not official_names:
        return warnings
    axis_text = "\n".join([
        _read(project_dir / SPEC),
        _read(project_dir / "01_大纲" / "总纲.md"),
    ])
    axis_names = _extract_axis_character_names(axis_text)
    if not axis_names:
        return warnings

    already_named = set()
    for issue in linkage_issues:
        if issue.get("area") in {"女主名册", "替换声明"}:
            already_named.update(issue.get("names", []))
    unknown = sorted((axis_names - official_names) - already_named)
    if unknown:
        warnings.append("故事规格/总纲提到但尚未建正式角色档案：" + "、".join(unknown[:8]))
    return warnings


def collect_character_roster_issues(project_dir: Path) -> list[dict[str, object]]:
    """检查总纲女主名册与正式角色档案是否同步。"""
    outline = _read(project_dir / "01_大纲" / "总纲.md")
    roster = _extract_outline_role_roster(outline, "女")
    outline_names = {item["name"] for item in roster}
    official_female = _official_female_character_names(project_dir)
    replacements = _replacement_declarations(project_dir)

    issues: list[dict[str, object]] = []
    missing = sorted(outline_names - official_female)
    if missing:
        issues.append({
            "level": "error",
            "area": "女主名册",
            "message": "总纲女主表提到但没有正式角色档案：" + "、".join(missing),
            "names": missing,
        })

    extra = sorted(official_female - outline_names)
    if extra:
        issues.append({
            "level": "error",
            "area": "女主名册",
            "message": "正式女主档案未进入总纲女主表：" + "、".join(extra),
            "names": extra,
        })

    stale_replacements = []
    for item in replacements:
        old_name = item["old_name"]
        new_name = item["new_name"]
        if old_name in outline_names and new_name not in outline_names:
            stale_replacements.append(f"{new_name} 替代 女{item['slot']}·{old_name}")
    if stale_replacements:
        issues.append({
            "level": "error",
            "area": "替换声明",
            "message": "角色档案声明替换旧女主，但总纲仍未同步：" + "；".join(stale_replacements),
            "names": [item.split(" 替代 ", 1)[0] for item in stale_replacements],
        })
    return issues


def collect_linkage_drift_issues(project_dir: Path) -> list[dict[str, object]]:
    """检查应该同步到上游/下游的设定是否出现语义漂移。"""
    issues: list[dict[str, object]] = []
    issues.extend(collect_character_roster_issues(project_dir))
    issues.extend(_story_spec_role_slot_issues(project_dir))
    issues.extend(_volume_outline_linkage_issues(project_dir))
    issues.extend(_character_sync_reminder_issues(project_dir))
    return issues


def render_story_consistency_review(project_dir: Path) -> str:
    warnings = collect_story_consistency_warnings(project_dir)
    if not warnings:
        return ""
    lines = [
        "## 本地一致性预警（审稿前硬检查）",
        "以下问题由文件系统和结构化规则直接发现，优先级高于模型审美判断：",
    ]
    lines.extend(f"- {item}" for item in warnings)
    lines += [
        "",
        "### 审查/改稿硬约束",
        "- 若正式角色档案与总纲/故事规格冲突，必须先指出冲突，不要只给泛泛建议。",
        "- 若故事规格、总纲、卷纲的阶段范围或角色功能位冲突，必须标出源文件并给出同步顺序。",
        "- AI 改稿只能写入 AI 草案，不能直接覆盖正式总纲、世界观或角色档案。",
        "- 同步女主名册时，必须明确保留哪个姓名、替换哪个旧名，以及对应功能位。",
    ]
    return "\n".join(lines)


def _extract_outline_role_roster(text: str, gender_prefix: str = "女") -> list[dict[str, str]]:
    pattern = rf"(?m)^\|\s*(?:\*\*)?{gender_prefix}([一二三四五六七八九十\d]+)[·\.、]([\u4e00-\u9fff]{{2,4}})(?:\*\*)?\s*\|"
    rows = []
    for match in re.finditer(pattern, text):
        rows.append({"slot": match.group(1), "name": match.group(2)})
    return rows


def _official_female_character_names(project_dir: Path) -> set[str]:
    char_dir = project_dir / "00_世界观" / "角色档案"
    if not char_dir.exists():
        return set()
    names: set[str] = set()
    for path in char_dir.glob("*.md"):
        if path.name == "角色模板.md":
            continue
        text = _read(path)
        if _is_female_lead_profile(text):
            names.add(path.stem)
    return names


def _is_female_lead_profile(text: str) -> bool:
    if re.search(r"(不是五女主|五女主之外|不是女主|反派/对手功能位)", text):
        return False
    if re.search(r"故事功能[^\n]{0,40}主角", text):
        return False
    if re.search(r"(?m)^-\s*\*\*姓名\*\*[：:]", text) and "她" in text[:4000]:
        return True
    return bool(re.search(r"(五位女主|五女主|女主中|女[一二三四五六七八九十\d]+[·\.、])", text))


def _replacement_declarations(project_dir: Path) -> list[dict[str, str]]:
    char_dir = project_dir / "00_世界观" / "角色档案"
    if not char_dir.exists():
        return []
    declarations = []
    pattern = re.compile(r"(?:替代|替换)[\s\S]{0,80}?女([一二三四五六七八九十\d]+)[·\.、]([\u4e00-\u9fff]{2,4})")
    for path in char_dir.glob("*.md"):
        if path.name == "角色模板.md":
            continue
        text = _read(path)
        for match in pattern.finditer(text):
            declarations.append({"new_name": path.stem, "slot": match.group(1), "old_name": match.group(2)})
    return declarations


def _story_spec_role_slot_issues(project_dir: Path) -> list[dict[str, object]]:
    spec = _read(project_dir / SPEC)
    if not spec:
        return []
    outline_roles = _extract_outline_role_candidates(_read(project_dir / "01_大纲" / "总纲.md"))
    pending = []
    names: list[str] = []
    for role in ["反派/对手", "挚友/同伴", "导师/障碍"]:
        pattern = rf"(?m)^\s*[-*]\s*(?:\*\*)?{re.escape(role)}(?:\*\*)?[：:]\s*待命名"
        if not re.search(pattern, spec):
            continue
        candidates = outline_roles.get(role, [])
        if candidates:
            pending.append(f"{role}（总纲已用：{'、'.join(candidates)}）")
            names.extend(candidates)
        else:
            pending.append(role)
    if not pending:
        return []
    return [{
        "level": "warning",
        "area": "故事规格角色位",
        "message": "故事规格主要角色位仍是待命名，未承接总纲/角色档案：" + "、".join(pending),
        "names": sorted(set(names)),
    }]


def _extract_outline_role_candidates(text: str) -> dict[str, list[str]]:
    role_map = {
        "反派/对手": "反派",
        "挚友/同伴": "挚友",
        "导师/障碍": "导师",
    }
    result: dict[str, list[str]] = {}
    for slot, label in role_map.items():
        names = []
        patterns = [
            rf"(?m)^\|\s*(?:\*\*)?{label}[·\.、：:]([\u4e00-\u9fff]{{2,4}})(?:\*\*)?\s*\|",
            rf"(?m)^\s*[-*]\s*(?:\*\*)?{label}(?:\*\*)?[：:]\s*([\u4e00-\u9fff]{{2,4}})",
        ]
        for pattern in patterns:
            for match in re.finditer(pattern, text):
                name = match.group(1).strip()
                if name.startswith("待"):
                    continue
                names.append(name)
        if names:
            result[slot] = sorted(set(names))
    return result


def _volume_outline_linkage_issues(project_dir: Path) -> list[dict[str, object]]:
    volume_dir = project_dir / "01_大纲" / "卷纲"
    if not volume_dir.exists():
        return []
    volume_infos = _extract_volume_infos(volume_dir)
    if not volume_infos:
        return []

    issues: list[dict[str, object]] = []
    placeholders = [item["file"] for item in volume_infos if item["placeholder"]]
    if placeholders:
        issues.append({
            "level": "warning",
            "area": "卷纲占位",
            "message": "卷纲仍是模板/占位，尚未承接正式总纲：" + "、".join(placeholders),
            "names": [],
        })

    act_ranges = _extract_outline_act_ranges(_read(project_dir / "01_大纲" / "总纲.md"))
    volume_ranges = [(item["start"], item["end"]) for item in volume_infos if item["start"] and item["end"]]
    if not act_ranges or not volume_ranges:
        return issues

    act_pairs = [(item["start"], item["end"]) for item in act_ranges]
    same_count_and_ranges = len(act_pairs) == len(volume_ranges) and all(a == b for a, b in zip(act_pairs, volume_ranges))
    outline_end = max(end for _, end in act_pairs)
    volume_end = max(end for _, end in volume_ranges)
    if volume_end > outline_end or (placeholders and not same_count_and_ranges):
        issues.append({
            "level": "warning",
            "area": "卷纲范围",
            "message": (
                "卷纲章节范围未承接总纲幕结构：总纲="
                + "、".join(f"第{start}-{end}章" for start, end in act_pairs)
                + "；卷纲="
                + "、".join(
                    f"{item['file']}=第{item['start']}-{item['end']}章"
                    for item in volume_infos
                    if item["start"] and item["end"]
                )
            ),
            "names": [],
        })
    return issues


def _extract_outline_act_ranges(text: str) -> list[dict[str, object]]:
    pattern = re.compile(
        r"(?m)^#{2,4}\s*(第[一二三四五六七八九十\d]+幕)[^\n]*?[（(]\s*第\s*(\d+)\s*章\s*[-—－~～至到]+\s*第?\s*(\d+)\s*章"
    )
    ranges = []
    for match in pattern.finditer(text):
        ranges.append({
            "label": match.group(1),
            "start": int(match.group(2)),
            "end": int(match.group(3)),
        })
    return ranges


def _extract_volume_infos(volume_dir: Path) -> list[dict[str, object]]:
    infos: list[dict[str, object]] = []
    for path in sorted(volume_dir.glob("第*卷.md")):
        text = _read(path)
        match = re.search(r"章节范围[：:]\s*(?:第)?0*(\d+)\s*(?:[-—－~～至到]+)\s*(?:第)?0*(\d+)", text)
        title = next((line.strip() for line in text.splitlines() if line.strip().startswith("#")), "")
        infos.append({
            "file": path.name,
            "start": int(match.group(1)) if match else 0,
            "end": int(match.group(2)) if match else 0,
            "placeholder": _is_volume_placeholder(title, text),
        })
    return infos


def _is_volume_placeholder(title: str, text: str) -> bool:
    template_markers = [
        "待命名",
        "本卷在全书中的结构任务",
        "本卷至少要形成",
        "需要延续上一卷",
    ]
    return any(marker in title or marker in text for marker in template_markers) or _contains_placeholder(text)


def _character_sync_reminder_issues(project_dir: Path) -> list[dict[str, object]]:
    char_dir = project_dir / "00_世界观" / "角色档案"
    if not char_dir.exists():
        return []
    outline = _read(project_dir / "01_大纲" / "总纲.md")
    spec = _read(project_dir / SPEC)
    unsynced = []
    names = []
    reminder_pattern = re.compile(r"(请同步|同步更新|以本档案为准|功能替换声明|替代《|替换《)")
    for path in sorted(char_dir.glob("*.md")):
        if path.name == "角色模板.md":
            continue
        text = _read(path)
        if not reminder_pattern.search(text):
            continue
        missing_targets = []
        if path.stem not in outline:
            missing_targets.append("总纲")
        if path.stem not in spec:
            missing_targets.append("故事规格")
        if missing_targets:
            unsynced.append(f"{path.stem}（未进入{'/'.join(missing_targets)}）")
            names.append(path.stem)
    if not unsynced:
        return []
    return [{
        "level": "warning",
        "area": "同步声明",
        "message": "角色档案含同步声明但上游仍未落地：" + "、".join(unsynced),
        "names": sorted(set(names)),
    }]


def _extract_axis_character_names(text: str) -> set[str]:
    stop_words = {
        "一句话",
        "一句话概括",
        "目标读者",
        "核心冲突",
        "主要角色",
        "类型卖点",
        "成功标准",
        "项目规格",
        "创作层面",
        "读者层面",
        "质量层面",
    }
    patterns = [
        r"(?m)^\s*[-*]\s*(?:\*\*)?(?:主角|反派/对手|挚友/同伴|导师/障碍)(?:\*\*)?[：:]\s*([\u4e00-\u9fff]{2,4})",
        r"(?m)^\|\s*(?:\*\*)?(?:(?:女|男)[一二三四五六七八九十\d]+|反派|挚友|导师)[·\.、：:]([\u4e00-\u9fff]{2,4})(?:\*\*)?\s*\|",
    ]
    names: set[str] = set()
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            name = match.group(1).strip()
            if name.startswith("待") or name in stop_words:
                continue
            names.add(name)
    return names


def suggest_next_actions(workflow: list[ProjectWorkflowStep], blockers: list[str], warnings: list[str]) -> list[str]:
    if blockers:
        return [blockers[0], "处理阻断项后重新生成质量报告"]
    for step in workflow:
        if step.status in {"missing", "draft"}:
            return [f"完善{step.name}", f"更新 {step.source_path} 后重新生成任务队列"]
    if warnings:
        return [warnings[0], "继续下一章写作闭环"]
    return ["进入下一章：章纲 -> 任务卡 -> 场景候选稿 -> 审计 -> 定稿记忆"]


def parse_chapter_num(name: str) -> int | None:
    match = re.search(r"第(\d+)章", name)
    return int(match.group(1)) if match else None


def _step(project_dir: Path, key: str, name: str, rel: str) -> ProjectWorkflowStep:
    path = project_dir / rel
    text = _read(path)
    if not path.exists():
        status = "missing"
        detail = "文件不存在"
    elif _contains_placeholder(text):
        status = "draft"
        detail = "仍有待补内容"
    elif len(_meaningful_text(text)) > 80:
        status = "ready"
        detail = "可用于指导创作"
    else:
        status = "draft"
        detail = "内容偏短，建议补充"
    return ProjectWorkflowStep(key=key, name=name, status=status, detail=detail, source_path=rel)


def _table_status(path: Path) -> str:
    text = _read(path)
    data_rows = [line for line in text.splitlines() if line.startswith("|") and "---" not in line and "编号" not in line]
    if not path.exists() or not data_rows:
        return "missing"
    if any("待回答" in line or "待办" in line for line in data_rows):
        return "active"
    return "ready"


def _writing_status(metrics: dict[str, int]) -> str:
    if metrics["finals"] and metrics["finals"] >= metrics["chapter_outlines"]:
        return "complete"
    if metrics["drafts"] or metrics["finals"]:
        return "active"
    return "missing"


def _task_card_status(path: Path) -> str:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("status", "")
    except (OSError, json.JSONDecodeError):
        return ""


def _contains_placeholder(text: str) -> bool:
    return bool(text and re.search("|".join(f"({pattern})" for pattern in PLACEHOLDER_PATTERNS), text))


def _meaningful_text(text: str) -> str:
    return re.sub(r"\s+", "", text.replace("待补充", ""))


def _count_table_rows(path: Path, keyword: str) -> int:
    text = _read(path)
    return sum(1 for line in text.splitlines() if line.startswith("|") and keyword in line)


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""
