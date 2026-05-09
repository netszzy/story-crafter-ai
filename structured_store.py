"""
Markdown-to-JSON helpers for V0.3 structured data.
"""

from __future__ import annotations

import re
import json
from pathlib import Path
from typing import Any

from novel_schemas import (
    CharacterState,
    ChapterMemory,
    ChapterTaskCard,
    ForeshadowingItem,
    ReviewIssue,
    ReviewReport,
    ScenePlan,
    now_iso,
    write_json_model,
)


def extract_title(markdown: str, fallback: str = "") -> str:
    for line in markdown.splitlines():
        if line.startswith("# "):
            return line.lstrip("# ").strip()
    return fallback


def parse_bullet_value(markdown: str, label: str) -> str:
    pattern = re.compile(rf"^\s*-\s*{re.escape(label)}[：:]\s*(.*)$", re.MULTILINE)
    match = pattern.search(markdown)
    return match.group(1).strip() if match else ""


def first_bullet_value(markdown: str, labels: list[str]) -> str:
    for label in labels:
        value = parse_bullet_value(markdown, label)
        if value:
            return value
    return ""


def _choice(value: str, allowed: set[str], default: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        return default
    if cleaned in allowed:
        return cleaned
    lowered = cleaned.lower()
    aliases = {
        "剧情": "plot",
        "主线": "plot",
        "过渡": "bridge",
        "桥段": "bridge",
        "内省": "interior",
        "心理": "interior",
        "氛围": "atmosphere",
        "气氛": "atmosphere",
        "尾声": "epilogue",
        "后日谈": "epilogue",
        "钩子": "hook",
        "悬念": "hook",
        "悬崖": "cliffhanger",
        "开放": "open",
        "回声": "echo",
        "呼应": "echo",
        "快": "fast",
        "中": "normal",
        "正常": "normal",
        "慢燃": "slow_burn",
        "慢热": "slow_burn",
    }
    candidate = aliases.get(cleaned) or aliases.get(lowered) or lowered
    return candidate if candidate in allowed else default


def section_text(markdown: str, heading: str) -> str:
    pattern = re.compile(rf"^##\s*{re.escape(heading)}\s*$([\s\S]*?)(?=^##\s+|\Z)", re.MULTILINE)
    match = pattern.search(markdown)
    return match.group(1).strip() if match else ""


def lines_from_section(markdown: str, heading: str) -> list[str]:
    text = section_text(markdown, heading)
    items = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("-"):
            items.append(stripped.lstrip("-").strip())
        elif stripped:
            items.append(stripped)
    return items


def parse_chapter_outline(
    chapter_num: int,
    outline: str,
    source_path: str = "",
    status: str = "draft",
) -> ChapterTaskCard:
    foreshadowing = lines_from_section(outline, "伏笔操作")
    forbidden = lines_from_section(outline, "禁止事项")
    planted = [item for item in foreshadowing if "埋" in item and "无" not in item]
    resolved = [item for item in foreshadowing if "收" in item and "无" not in item]
    return ChapterTaskCard(
        chapter_number=chapter_num,
        title=extract_title(outline, f"第{chapter_num:03d}章"),
        status=status,
        chapter_mode=_choice(
            first_bullet_value(outline, ["章节模式", "ChapterMode", "chapter_mode"]),
            {"plot", "bridge", "interior", "atmosphere", "epilogue"},
            "plot",
        ),
        ending_style=_choice(
            first_bullet_value(outline, ["结尾方式", "章末方式", "ending_style"]),
            {"hook", "cliffhanger", "open", "echo"},
            "hook",
        ),
        pacing=_choice(
            first_bullet_value(outline, ["节奏", "pacing"]),
            {"fast", "normal", "slow_burn"},
            "normal",
        ),
        style_profile=first_bullet_value(outline, ["风格档案", "style_profile"]),
        pov_character=parse_bullet_value(outline, "视角人物"),
        target_words=parse_bullet_value(outline, "字数目标"),
        timeline=parse_bullet_value(outline, "时间线"),
        core_event=section_text(outline, "核心事件"),
        emotional_curve=section_text(outline, "情感弧线"),
        foreshadowing_planted=planted,
        foreshadowing_resolved=resolved,
        ending_hook=section_text(outline, "章末悬念"),
        forbidden=forbidden,
        source_path=source_path,
    )


def task_card_path(project_dir: Path, chapter_num: int) -> Path:
    return project_dir / "01_大纲" / "章纲" / f"第{chapter_num:03d}章_task_card.json"


def read_task_card(project_dir: Path, chapter_num: int) -> ChapterTaskCard | None:
    path = task_card_path(project_dir, chapter_num)
    if not path.exists():
        return None
    return ChapterTaskCard.model_validate_json(path.read_text(encoding="utf-8"))


def write_task_card(project_dir: Path, card: ChapterTaskCard) -> Path:
    card.updated_at = now_iso()
    return write_json_model(task_card_path(project_dir, card.chapter_number), card)


def sync_task_card_from_outline(
    project_dir: Path,
    chapter_num: int,
    outline: str,
    preserve_confirmation: bool = True,
    llm: Any | None = None,
    context: str = "",
) -> ChapterTaskCard:
    existing = read_task_card(project_dir, chapter_num)
    status = "confirmed" if preserve_confirmation and existing and existing.status == "confirmed" else "draft"
    card = parse_chapter_outline(
        chapter_num,
        outline,
        f"01_大纲/章纲/第{chapter_num:03d}章.md",
        status=status,
    )
    if llm is not None:
        hints = extract_foreshadowing_hints_with_llm(llm, card, outline, context)
        merge_foreshadowing_hints(card, hints)
    if existing and existing.status == "confirmed" and preserve_confirmation:
        card.confirmed_at = existing.confirmed_at
    if existing:
        if card.chapter_mode == "plot" and existing.chapter_mode != "plot":
            card.chapter_mode = existing.chapter_mode
        if card.ending_style == "hook" and existing.ending_style != "hook":
            card.ending_style = existing.ending_style
        if card.pacing == "normal" and existing.pacing != "normal":
            card.pacing = existing.pacing
        if not card.style_profile and existing.style_profile:
            card.style_profile = existing.style_profile
        if not card.technique_focus and existing.technique_focus:
            card.technique_focus = existing.technique_focus
    write_task_card(project_dir, card)
    return card


def confirm_task_card(project_dir: Path, chapter_num: int) -> ChapterTaskCard:
    card = read_task_card(project_dir, chapter_num)
    if card is None:
        outline_path = project_dir / "01_大纲" / "章纲" / f"第{chapter_num:03d}章.md"
        outline = outline_path.read_text(encoding="utf-8") if outline_path.exists() else ""
        card = parse_chapter_outline(
            chapter_num,
            outline,
            f"01_大纲/章纲/第{chapter_num:03d}章.md",
            status="confirmed",
        )
    card.status = "confirmed"
    card.confirmed_at = now_iso()
    write_task_card(project_dir, card)
    return card


def chapter_dir(project_dir: Path, chapter_num: int) -> Path:
    return project_dir / "01_大纲" / "章纲" / f"第{chapter_num:03d}章_scenes"


def scene_plan_path(project_dir: Path, chapter_num: int) -> Path:
    return chapter_dir(project_dir, chapter_num) / "scene_plan.json"


def build_scene_plan_from_task_card(card: ChapterTaskCard) -> list[ScenePlan]:
    title = card.title or f"第{card.chapter_number:03d}章"
    pov = card.pov_character
    core_event = card.core_event or "推进本章核心事件"
    ending_hook = card.ending_hook or "保留章末张力"
    forbidden = card.forbidden
    required = []
    required.extend(card.foreshadowing_planted)
    required.extend(card.foreshadowing_resolved)
    return [
        ScenePlan(
            chapter_number=card.chapter_number,
            scene_number=1,
            title=f"{title}：开场压力",
            pov_character=pov,
            scene_goal=f"建立本章入口并触发事件：{core_event}",
            conflict="主角当前目标与外部压力发生碰撞。",
            emotional_tone="警觉、压抑",
            required_information=required[:2],
            forbidden_information=forbidden,
            estimated_words=1200,
        ),
        ScenePlan(
            chapter_number=card.chapter_number,
            scene_number=2,
            title=f"{title}：冲突升级",
            pov_character=pov,
            scene_goal=f"推进核心事件并制造选择压力：{card.emotional_curve or core_event}",
            conflict="人物必须在不完整信息下做出选择。",
            emotional_tone="紧张、迟疑",
            required_information=required[2:4],
            forbidden_information=forbidden,
            estimated_words=1400,
        ),
        ScenePlan(
            chapter_number=card.chapter_number,
            scene_number=3,
            title=f"{title}：章末钩子",
            pov_character=pov,
            scene_goal=f"完成本章阶段结果，并落到钩子：{ending_hook}",
            conflict="短暂解决带出更大的未知。",
            emotional_tone="悬疑、收束",
            required_information=required[4:],
            forbidden_information=forbidden,
            estimated_words=1000,
        ),
    ]


def extract_foreshadowing_hints_with_llm(
    llm: Any,
    card: ChapterTaskCard,
    outline: str,
    context: str = "",
) -> dict[str, list[str]]:
    system_prompt = (
        "你是中文长篇小说伏笔编辑。你的任务是从章纲和任务卡中识别显性与隐性伏笔，"
        "只输出 JSON，不要解释。"
    )
    user_prompt = f"""请识别本章需要登记的伏笔操作。

## 联动硬约束
- 项目上下文是硬约束，不是背景参考。
- 伏笔必须服务故事规格、核心冲突、类型卖点、总纲和角色弧线。
- 不要登记与主线无关的孤立细节；若章纲里出现孤立细节，请忽略或归入 open question。

## 输出格式
只输出一个 JSON 对象：
{{
  "planted": ["本章埋下但可能没有写明'埋下：'的伏笔"],
  "resolved": ["本章收回、解释、兑现的伏笔"]
}}

## 项目上下文
{context}

## 任务卡
{card.model_dump_json(indent=2)}

## 章纲
{outline}
"""
    try:
        text = llm.assist_text(
            system_prompt,
            user_prompt,
            workflow="foreshadowing_extract",
            role="critic",
            max_tokens=2000,
            temperature=0.1,
        )
        data = _extract_json(text)
        return {
            "planted": _string_list(data.get("planted", [])),
            "resolved": _string_list(data.get("resolved", [])),
        }
    except Exception:
        return {"planted": [], "resolved": []}


def merge_foreshadowing_hints(card: ChapterTaskCard, hints: dict[str, list[str]]) -> ChapterTaskCard:
    card.foreshadowing_planted = _dedupe_keep_order([
        *card.foreshadowing_planted,
        *hints.get("planted", []),
    ])
    card.foreshadowing_resolved = _dedupe_keep_order([
        *card.foreshadowing_resolved,
        *hints.get("resolved", []),
    ])
    return card


def build_scene_plan_with_llm(
    llm: Any,
    card: ChapterTaskCard,
    context: str = "",
) -> list[ScenePlan]:
    system_prompt = (
        "你是中文长篇小说结构编辑。请把章节任务卡拆成自然数量的场景，"
        "输出严格 JSON 数组，不要解释。"
    )
    user_prompt = f"""请根据任务卡生成本章场景计划。

## 硬性要求
- 按故事需要生成 2-6 个场景，不要固定三段式。
- 每个场景都必须推进明确目标、冲突和情绪变化。
- 必须把任务卡里的伏笔、禁止事项、章末钩子分配到合适场景。
- 必须服务项目轴中的故事规格、文风档案、总纲和目标读者期待；不要生成与主线无关的孤立场景。
- 每个场景的 scene_goal 要写清楚推进了哪一项核心冲突、人物关系或类型卖点。
- 只输出 JSON 数组，每个对象字段如下：
  chapter_number, scene_number, title, pov_character, location, scene_goal,
  conflict, emotional_tone, required_information, forbidden_information, estimated_words

## 项目上下文
{context}

## 章节任务卡
{card.model_dump_json(indent=2)}
"""
    text = llm.assist_text(
        system_prompt,
        user_prompt,
        workflow="scene_plan",
        role="structure_editor",
        max_tokens=6000,
        temperature=0.2,
    )
    data = _extract_json(text)
    if isinstance(data, dict):
        data = data.get("scenes", [])
    scenes: list[ScenePlan] = []
    for idx, item in enumerate(data if isinstance(data, list) else [], start=1):
        if not isinstance(item, dict):
            continue
        item.setdefault("chapter_number", card.chapter_number)
        item.setdefault("scene_number", idx)
        item.setdefault("pov_character", card.pov_character)
        item.setdefault("forbidden_information", card.forbidden)
        scenes.append(ScenePlan.model_validate(item))
    if not scenes:
        raise ValueError("LLM 未返回可用场景计划")
    scenes = sorted(scenes, key=lambda item: item.scene_number)
    for idx, scene in enumerate(scenes, start=1):
        scene.chapter_number = card.chapter_number
        scene.scene_number = idx
        scene.status = "planned"
    return scenes


def write_scene_plan(project_dir: Path, chapter_num: int, scenes: list[ScenePlan]) -> Path:
    target = scene_plan_path(project_dir, chapter_num)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps([scene.model_dump() for scene in scenes], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def read_scene_plan(project_dir: Path, chapter_num: int) -> list[ScenePlan]:
    path = scene_plan_path(project_dir, chapter_num)
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [ScenePlan.model_validate(item) for item in data]


def sync_scene_plan_from_task_card(
    project_dir: Path,
    chapter_num: int,
    llm: Any | None = None,
    context: str = "",
) -> list[ScenePlan]:
    card = read_task_card(project_dir, chapter_num)
    if card is None:
        outline_path = project_dir / "01_大纲" / "章纲" / f"第{chapter_num:03d}章.md"
        outline = outline_path.read_text(encoding="utf-8") if outline_path.exists() else ""
        card = sync_task_card_from_outline(project_dir, chapter_num, outline)
    existing = {scene.scene_number: scene for scene in read_scene_plan(project_dir, chapter_num)}
    try:
        scenes = build_scene_plan_with_llm(llm, card, context) if llm is not None else build_scene_plan_from_task_card(card)
    except Exception:
        scenes = build_scene_plan_from_task_card(card)
    for scene in scenes:
        old = existing.get(scene.scene_number)
        if old and old.selected_draft_path:
            scene.selected_draft_path = old.selected_draft_path
            scene.status = old.status
    write_scene_plan(project_dir, chapter_num, scenes)
    return scenes


def update_scene_status(
    project_dir: Path,
    chapter_num: int,
    scene_number: int,
    status: str,
    selected_draft_path: str | None = None,
) -> list[ScenePlan]:
    scenes = read_scene_plan(project_dir, chapter_num)
    for scene in scenes:
        if scene.scene_number == scene_number:
            scene.status = status
            if selected_draft_path is not None:
                scene.selected_draft_path = selected_draft_path
            scene.updated_at = now_iso()
    write_scene_plan(project_dir, chapter_num, scenes)
    return scenes


def next_scene_draft_version(project_dir: Path, chapter_num: int, scene_number: int) -> int:
    scene_dir = project_dir / "02_正文" / f"第{chapter_num:03d}章_scenes"
    versions = []
    for path in scene_dir.glob(f"scene_{scene_number:03d}_draft_v*.md"):
        match = re.search(r"_v(\d+)\.md$", path.name)
        if match:
            versions.append(int(match.group(1)))
    return (max(versions) + 1) if versions else 1


def list_scene_drafts(project_dir: Path, chapter_num: int, scene_number: int) -> list[Path]:
    scene_dir = project_dir / "02_正文" / f"第{chapter_num:03d}章_scenes"
    return sorted(
        scene_dir.glob(f"scene_{scene_number:03d}_draft_v*.md"),
        key=lambda path: _scene_draft_version(path),
    )


def select_scene_draft(project_dir: Path, chapter_num: int, scene_number: int, draft_path: str) -> list[ScenePlan]:
    full_path = project_dir / draft_path
    if not full_path.exists():
        raise FileNotFoundError(f"场景候选稿不存在：{draft_path}")
    return update_scene_status(project_dir, chapter_num, scene_number, "selected", draft_path)


def _scene_draft_version(path: Path) -> int:
    match = re.search(r"_v(\d+)\.md$", path.name)
    return int(match.group(1)) if match else 0


def parse_review_report(
    chapter_num: int,
    audit_text: str,
    model_name: str = "",
    source_markdown_path: str = "",
) -> ReviewReport:
    issue_chunks = re.split(r"(?=-\s*【问题位置】)", audit_text)
    issues: list[ReviewIssue] = []
    for chunk in issue_chunks:
        if "【问题位置】" not in chunk:
            continue
        issues.append(
            ReviewIssue(
                location=_extract_tag(chunk, "问题位置"),
                basis=_extract_tag(chunk, "冲突依据"),
                suggestion=_extract_tag(chunk, "修改建议"),
                severity=_infer_severity(chunk),
            )
        )
    return ReviewReport(
        target_id=f"ch{chapter_num:03d}",
        chapter_number=chapter_num,
        model_name=model_name,
        source_markdown_path=source_markdown_path,
        issues=issues,
        raw_text=audit_text,
    )


def build_chapter_memory(
    chapter_num: int,
    chapter_text: str,
    summary: str,
    outline: str = "",
    source_markdown_path: str = "",
    character_state_changes: dict[str, str] | None = None,
) -> ChapterMemory:
    title = extract_title(chapter_text) or extract_title(outline, f"第{chapter_num:03d}章")
    lines = [line.strip("- ").strip() for line in summary.splitlines() if line.strip()]
    events = [line for line in lines if "核心事件" in line]
    added = [line for line in lines if "新伏笔" in line]
    resolved = [line for line in lines if "收回伏笔" in line or "回收伏笔" in line]
    return ChapterMemory(
        chapter_number=chapter_num,
        title=title,
        source_markdown_path=source_markdown_path,
        summary=summary,
        events=events or [summary.strip()[:300]],
        character_state_changes=character_state_changes or {},
        foreshadowing_added=added,
        foreshadowing_resolved=resolved,
        open_questions=["请人工核对人物状态、伏笔状态和时间线。"],
    )


def character_state_json_path(project_dir: Path) -> Path:
    return project_dir / "03_滚动记忆" / "人物状态.json"


def read_character_states(project_dir: Path) -> dict[str, CharacterState]:
    path = character_state_json_path(project_dir)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    raw_items = data.get("characters", data if isinstance(data, list) else [])
    states: dict[str, CharacterState] = {}
    for item in raw_items:
        try:
            state = CharacterState.model_validate(item)
        except Exception:
            continue
        if state.name.strip():
            states[state.name.strip()] = state
    return states


def render_character_states_markdown(states: dict[str, CharacterState]) -> str:
    lines = [
        "# 人物状态表",
        "",
        "（V1.6 自动维护；定稿后可人工修订。结构化镜像见 `人物状态.json`。）",
        "",
    ]
    if not states:
        lines.extend(
            [
                "## 暂无人物状态",
                "- 定稿并更新记忆后，系统会从章节正文抽取角色位置、身体、情绪、已知信息和持有物。",
                "",
            ]
        )
        return "\n".join(lines)

    for state in sorted(states.values(), key=lambda item: item.name):
        lines.extend(
            [
                f"## {state.name}",
                f"- 最近更新章节：第{state.chapter_number:03d}章" if state.chapter_number else "- 最近更新章节：待确认",
                f"- 位置：{state.location or '待确认'}",
                f"- 身体状态：{state.physical_state or '待确认'}",
                f"- 情绪状态：{state.emotional_state or '待确认'}",
                f"- 当前目标：{state.goal or '待确认'}",
                f"- 最新获知信息：{_join_or_placeholder(state.known_information)}",
                f"- 持有物品：{_join_or_placeholder(state.possessions)}",
                f"- 关系变化：{_join_or_placeholder(state.relationship_changes)}",
                f"- 来源：{state.source_path or '待确认'}",
                "",
            ]
        )
    return "\n".join(lines)


def write_character_states_json(project_dir: Path, states: dict[str, CharacterState]) -> Path:
    target = character_state_json_path(project_dir)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": "1.6",
        "characters": [
            state.model_dump() for state in sorted(states.values(), key=lambda item: item.name)
        ],
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def write_character_states_markdown(project_dir: Path, states: dict[str, CharacterState]) -> Path:
    target = project_dir / "03_滚动记忆" / "人物状态表.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_character_states_markdown(states) + "\n", encoding="utf-8")
    return target


def update_character_states_with_llm(
    project_dir: Path,
    chapter_num: int,
    chapter_text: str,
    summary: str,
    llm: Any,
    outline: str = "",
) -> dict[str, Any]:
    existing = read_character_states(project_dir)
    try:
        from prompt_assembly import build_axis_context

        project_context = build_axis_context(project_dir)
    except Exception:
        project_context = ""
    extracted = extract_character_states_with_llm(
        llm,
        chapter_num,
        chapter_text,
        summary,
        outline,
        existing,
        project_context,
    )
    changes: dict[str, str] = {}
    for state in extracted:
        name = state.name.strip()
        if not name:
            continue
        state.name = name
        state.chapter_number = chapter_num
        state.source_path = f"02_正文/第{chapter_num:03d}章_定稿.md"
        state.updated_at = now_iso()
        existing[name] = merge_character_state(existing.get(name), state)
        changes[name] = summarize_character_state_change(state)

    markdown_path = write_character_states_markdown(project_dir, existing)
    json_path = write_character_states_json(project_dir, existing)
    return {"markdown": markdown_path, "json": json_path, "changes": changes}


def extract_character_states_with_llm(
    llm: Any,
    chapter_num: int,
    chapter_text: str,
    summary: str,
    outline: str,
    existing: dict[str, CharacterState],
    project_context: str = "",
) -> list[CharacterState]:
    system_prompt = (
        "你是长篇小说连续性编辑，负责维护人物状态表。"
        "只根据本章定稿正文和章纲输出人物状态增量，不要编造正文没有支持的信息。"
    )
    existing_json = json.dumps(
        [state.model_dump() for state in existing.values()],
        ensure_ascii=False,
        indent=2,
    )
    user_prompt = f"""请抽取第{chapter_num:03d}章定稿后的人物状态增量。

## 联动硬约束
- 人物状态必须按项目轴、故事规格、世界规则和角色弧线理解，不要只做流水账。
- 只记录正文有证据支撑的变化；不确定信息保留为空，不要替作者补设定。
- 当前目标、关系变化、已知信息要能服务后续章节生成和一致性审计。

## 输出格式
只输出一个 JSON 对象：
{{
  "characters": [
    {{
      "name": "角色名",
      "location": "章节结束时所在位置或待确认",
      "physical_state": "身体状态",
      "emotional_state": "情绪状态",
      "known_information": ["本章后此角色明确知道的信息"],
      "possessions": ["章节结束时持有的重要物品"],
      "goal": "当前目标",
      "relationship_changes": ["与其他角色的关系变化"]
    }}
  ]
}}

## 已有人物状态
{existing_json}

## 项目轴
{project_context[:4000]}

## 章纲
{outline[:3000]}

## 摘要
{summary}

## 本章定稿正文
{chapter_text[:7000]}
"""
    try:
        text = llm.assist_text(
            system_prompt,
            user_prompt,
            workflow="character_state_update",
            role="continuity_editor",
            max_tokens=4000,
            temperature=0.1,
        )
        data = _extract_json(text)
    except Exception:
        return []
    raw_items = data.get("characters", []) if isinstance(data, dict) else []
    states: list[CharacterState] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        try:
            states.append(CharacterState.model_validate(item))
        except Exception:
            continue
    return states


def merge_character_state(old: CharacterState | None, new: CharacterState) -> CharacterState:
    if old is None:
        return new
    merged = old.model_copy(deep=True)
    for field in ["location", "physical_state", "emotional_state", "goal", "source_path"]:
        value = getattr(new, field)
        if isinstance(value, str) and value.strip():
            setattr(merged, field, value.strip())
    merged.known_information = _dedupe_keep_order([*old.known_information, *new.known_information])
    merged.possessions = _dedupe_keep_order([*old.possessions, *new.possessions])
    merged.relationship_changes = _dedupe_keep_order([*old.relationship_changes, *new.relationship_changes])
    merged.chapter_number = new.chapter_number or old.chapter_number
    merged.updated_at = new.updated_at or now_iso()
    return merged


def summarize_character_state_change(state: CharacterState) -> str:
    parts = []
    if state.location:
        parts.append(f"位置：{state.location}")
    if state.emotional_state:
        parts.append(f"情绪：{state.emotional_state}")
    if state.goal:
        parts.append(f"目标：{state.goal}")
    if state.known_information:
        parts.append(f"新知：{'; '.join(state.known_information[:3])}")
    return "；".join(parts) or "本章有状态增量，待人工复核。"


def _join_or_placeholder(items: list[str]) -> str:
    cleaned = [item for item in items if item.strip()]
    return "；".join(cleaned) if cleaned else "待确认"


def parse_foreshadow_table(markdown: str) -> list[ForeshadowingItem]:
    items: list[ForeshadowingItem] = []
    for line in markdown.splitlines():
        if not line.startswith("|") or "---" in line or "编号" in line:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 5:
            continue
        status = "unknown"
        if "待回收" in cells[3] or "🟡" in cells[3]:
            status = "pending"
        elif "已回收" in cells[3] or "🟢" in cells[3] or "✅" in cells[3]:
            status = "resolved"
        elif "作废" in cells[3] or "🔴" in cells[3]:
            status = "abandoned"
        items.append(
            ForeshadowingItem(
                id=cells[0],
                planted_chapter=cells[1],
                content=cells[2],
                status=status,
                planned_resolution_chapter=cells[4],
            )
        )
    return items


def write_chapter_task_card_json(project_dir: Path, chapter_num: int, outline: str) -> Path:
    return write_task_card(project_dir, sync_task_card_from_outline(project_dir, chapter_num, outline))


def write_review_json(project_dir: Path, chapter_num: int, audit_text: str, model_name: str = "") -> Path:
    rel = f"04_审核日志/第{chapter_num:03d}章_审计.json"
    model = parse_review_report(chapter_num, audit_text, model_name, f"04_审核日志/第{chapter_num:03d}章_审计.md")
    return write_json_model(project_dir / rel, model)


def write_review_json_for_source(
    project_dir: Path,
    chapter_num: int,
    audit_text: str,
    model_name: str = "",
    source_markdown_path: str = "",
    target_id: str = "",
) -> Path:
    rel = source_markdown_path.replace(".md", ".json") if source_markdown_path else f"04_审核日志/第{chapter_num:03d}章_审计.json"
    model = parse_review_report(
        chapter_num,
        audit_text,
        model_name,
        source_markdown_path or f"04_审核日志/第{chapter_num:03d}章_审计.md",
    )
    if target_id:
        model.target_id = target_id
    return write_json_model(project_dir / rel, model)


def write_memory_json(
    project_dir: Path,
    chapter_num: int,
    chapter_text: str,
    summary: str,
    outline: str = "",
    character_state_changes: dict[str, str] | None = None,
) -> Path:
    rel = f"03_滚动记忆/章节记忆/第{chapter_num:03d}章_memory.json"
    model = build_chapter_memory(
        chapter_num,
        chapter_text,
        summary,
        outline,
        f"02_正文/第{chapter_num:03d}章_定稿.md",
        character_state_changes,
    )
    return write_json_model(project_dir / rel, model)


def write_foreshadow_json(project_dir: Path, foreshadow_markdown: str) -> Path:
    target = project_dir / "03_滚动记忆" / "伏笔追踪.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    data = [item.model_dump() for item in parse_foreshadow_table(foreshadow_markdown)]
    import json

    target.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def _extract_tag(text: str, tag: str) -> str:
    pattern = re.compile(rf"【{re.escape(tag)}】\s*(.*?)(?=\n\s*(?:【|$)|\Z)", re.S)
    match = pattern.search(text)
    return " ".join(match.group(1).split()) if match else ""


def _infer_severity(text: str) -> str:
    if any(word in text for word in ["硬伤", "矛盾", "冲突", "错误"]):
        return "high"
    if any(word in text for word in ["占位符", "遗漏", "过早"]):
        return "medium"
    return "unknown"


def _extract_json(text: str) -> Any:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass
    match = re.search(r"(\{[\s\S]*\}|\[[\s\S]*\])", stripped)
    if not match:
        raise ValueError("未找到 JSON")
    return json.loads(match.group(1))


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        key = re.sub(r"\s+", "", item)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result
