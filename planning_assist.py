"""
Planning assistance helpers for V0.7.

These helpers generate draft files for early novel-planning artifacts. They do
not overwrite canonical project documents; every output goes into an AI草案
folder for human review.
"""

from __future__ import annotations

import os
import re
import shutil
from datetime import datetime
from pathlib import Path

from llm_router import LLMRouter
from project_center import render_story_consistency_review
from prompt_assembly import (
    append_planning_context,
    build_planning_context,
    parse_story_spec,
    planning_linkage_contract,
    spec_summary_block,
)


PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_PLANNING_PROMPT_CHAR_LIMIT = 28000
DEFAULT_PLANNING_CONTINUATION_ROUNDS = 3
OUTLINE_END_MARKER = "[[END_OF_OUTLINE]]"

PLANNING_INPUT_LIMITS = {
    "brief": 4000,
    "world": 6000,
    "style": 2500,
    "outline": 8000,
    "current_outline": 8000,
    "foreshadowing": 3000,
    "character": 6000,
    "characters": 4000,
    "template": 3000,
    "review": 6000,
    "chapter_outline": 6000,
    "recent_summary": 3000,
    "consistency": 3000,
}


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def compact_planning_text(text: str, limit: int, label: str = "输入内容") -> str:
    """Cap long planning inputs while preserving the beginning and ending context."""
    text = (text or "").strip()
    if not text or limit <= 0 or len(text) <= limit:
        return text
    marker = (
        f"\n\n[系统已压缩：{label} 原文约 {len(text)} 字符，"
        "已保留开头和结尾；中段内容如需精修，请分段提交。]\n\n"
    )
    if limit <= len(marker) + 20:
        return text[:limit].rstrip()
    remaining = limit - len(marker)
    head_len = max(1, int(remaining * 0.62))
    tail_len = max(1, remaining - head_len)
    return f"{text[:head_len].rstrip()}{marker}{text[-tail_len:].lstrip()}"


def _planning_prompt_limit() -> int:
    raw = os.getenv("NOVEL_PLANNING_PROMPT_CHAR_LIMIT", "").strip()
    try:
        value = int(raw) if raw else DEFAULT_PLANNING_PROMPT_CHAR_LIMIT
    except ValueError:
        value = DEFAULT_PLANNING_PROMPT_CHAR_LIMIT
    return max(8000, min(value, 120000))


def _planning_continuation_rounds() -> int:
    raw = os.getenv("NOVEL_PLANNING_CONTINUATION_ROUNDS", "").strip()
    try:
        value = int(raw) if raw else DEFAULT_PLANNING_CONTINUATION_ROUNDS
    except ValueError:
        value = DEFAULT_PLANNING_CONTINUATION_ROUNDS
    return max(0, min(value, 8))


def _input_limit(key: str, fallback: int = 4000) -> int:
    return PLANNING_INPUT_LIMITS.get(key, fallback)


def load_planning_text(path: Path, key: str, label: str | None = None) -> str:
    return compact_planning_text(load_text(path), _input_limit(key), label or path.name)


def render_template(template: str, values: dict[str, str]) -> str:
    rendered = template
    for key, value in values.items():
        rendered = rendered.replace("{{ " + key + " }}", value)
        rendered = rendered.replace("{{" + key + "}}", value)
    return rendered


def save_draft(project_dir: Path, rel_dir: str, prefix: str, content: str) -> Path:
    target_dir = project_dir / rel_dir / "AI草案"
    target_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = target_dir / f"{prefix}_{timestamp}.md"
    target = unique_path(target)
    target.write_text(content.strip() + "\n", encoding="utf-8")
    return target


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 1000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise FileExistsError(f"无法生成唯一文件名：{path}")


def safe_filename(name: str, fallback: str = "角色") -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\s]+', "_", name.strip()).strip("_")
    return cleaned[:40] or fallback


def apply_mock_env(enabled: bool) -> None:
    if enabled:
        os.environ["NOVEL_LLM_MODE"] = "mock"
        os.environ["NOVEL_RAG_MODE"] = "mock"


def add_project_linkage(project_dir: Path, user_prompt: str, target: str) -> str:
    linked = append_planning_context(user_prompt, build_planning_context(project_dir, target=target))
    return compact_planning_text(linked, _planning_prompt_limit(), "完整策划提示词")


def _consistency_context(project_dir: Path) -> str:
    return compact_planning_text(
        render_story_consistency_review(project_dir) or "暂无",
        _input_limit("consistency"),
        "本地一致性预警",
    )


def _strip_end_marker(text: str, marker: str) -> str:
    return (text or "").replace(marker, "").strip()


def _looks_mock_router(router: LLMRouter) -> bool:
    return getattr(router, "mode", "") == "mock"


def _assist_text_with_continuation(
    router: LLMRouter,
    system_prompt: str,
    user_prompt: str,
    *,
    workflow: str,
    role: str = "director",
    max_tokens: int | None = None,
    end_marker: str = OUTLINE_END_MARKER,
    continuation_label: str = "长文草案",
) -> str:
    """Generate long planning text and continue if the model output was cut off."""
    marked_prompt = (
        f"{user_prompt.rstrip()}\n\n"
        f"## 完成标记\n"
        f"请完整输出{continuation_label}。如果已经全部写完，最后单独一行写：{end_marker}\n"
        "如果还没写完，不要提前写完成标记。"
    )
    marked_prompt = compact_planning_text(marked_prompt, _planning_prompt_limit(), f"{continuation_label}提示词")
    content = router.assist_text(
        system_prompt,
        marked_prompt,
        workflow=workflow,
        role=role,
        max_tokens=max_tokens,
    )
    if end_marker in content or _looks_mock_router(router):
        return _strip_end_marker(content, end_marker)

    pieces = [content.strip()]
    max_rounds = _planning_continuation_rounds()
    for round_num in range(1, max_rounds + 1):
        tail = compact_planning_text("\n\n".join(pieces)[-5000:], 5000, f"{continuation_label}已生成尾段")
        continue_prompt = (
            f"上一轮{continuation_label}输出疑似因为长度限制中断。请从断点继续写，不要重写已完成部分。\n\n"
            f"## 已生成内容尾段\n{tail}\n\n"
            "## 续写要求\n"
            "- 只输出后续缺失内容。\n"
            "- 保持 Markdown 层级、编号和语气连续。\n"
            "- 如果这次已经全部写完，最后单独一行写完成标记："
            f"{end_marker}\n"
        )
        part = router.assist_text(
            system_prompt,
            continue_prompt,
            workflow=f"{workflow}_continue_{round_num}",
            role=role,
            max_tokens=max_tokens,
        )
        pieces.append(_strip_end_marker(part, end_marker))
        if end_marker in part:
            break
    return "\n\n".join(piece for piece in pieces if piece).strip()


def _outline_output_max_tokens(router: LLMRouter) -> int | None:
    raw = os.getenv("NOVEL_OUTLINE_MAX_TOKENS", "").strip()
    if raw:
        try:
            return max(2000, min(int(raw), 60000))
        except ValueError:
            pass
    provider = getattr(router, "ASSIST_PROVIDER", "")
    if provider == "deepseek":
        return getattr(router, "DEEPSEEK_MAX_TOKENS", None)
    return max(getattr(router, "CLAUDE_MAX_TOKENS", 8000), 12000)


def _revise_outline_with_continuation(
    router: LLMRouter,
    system_prompt: str,
    user_prompt: str,
    *,
    workflow: str,
    end_marker: str = OUTLINE_END_MARKER,
) -> str:
    marked_prompt = (
        f"{user_prompt.rstrip()}\n\n"
        "## 完成标记\n"
        f"请完整输出改进版总纲。全部写完后，最后单独一行写：{end_marker}\n"
        "如果还没写完，不要提前写完成标记。"
    )
    marked_prompt = compact_planning_text(marked_prompt, _planning_prompt_limit(), "改进版总纲提示词")
    content = router.revise_text(
        system_prompt,
        marked_prompt,
        workflow=workflow,
        role="reviser",
        max_tokens=_outline_output_max_tokens(router),
    )
    if end_marker in content or _looks_mock_router(router):
        return _strip_end_marker(content, end_marker)

    pieces = [content.strip()]
    for round_num in range(1, _planning_continuation_rounds() + 1):
        tail = compact_planning_text("\n\n".join(pieces)[-5000:], 5000, "改进版总纲已生成尾段")
        continue_prompt = (
            "上一轮改进版总纲输出疑似因为长度限制中断。请从断点继续写，不要重写已完成部分。\n\n"
            f"## 已生成内容尾段\n{tail}\n\n"
            "## 续写要求\n"
            "- 只输出后续缺失内容。\n"
            "- 保持 Markdown 层级、编号和语气连续。\n"
            f"- 如果这次已经全部写完，最后单独一行写完成标记：{end_marker}\n"
        )
        part = router.revise_text(
            system_prompt,
            continue_prompt,
            workflow=f"{workflow}_continue_{round_num}",
            role="reviser",
            max_tokens=_outline_output_max_tokens(router),
        )
        pieces.append(_strip_end_marker(part, end_marker))
        if end_marker in part:
            break
    return "\n\n".join(piece for piece in pieces if piece).strip()


def add_visible_linkage_header(project_dir: Path, content: str, target: str) -> str:
    if "项目规格对齐" in content[:500]:
        return content
    spec_block = spec_summary_block(parse_story_spec(project_dir))
    contract = planning_linkage_contract(target)
    if not spec_block and not contract:
        return content
    label = {
        "world": "世界观草案",
        "outline": "总纲草案",
        "volume": "卷纲草案",
        "character": "角色档案草案",
        "character_batch": "批量角色档案草案",
        "chapter": "章纲草案",
    }.get(target, "策划草案")
    lines = [
        f"## 项目规格对齐（{label}）",
        "",
        "### 已读取的故事规格",
        spec_block or "- 故事规格尚未补全；请先在中台完善后再生成草案。",
        "",
        "### 本草案必须执行的联动要求",
        contract or "- 按项目轴约束生成。",
        "",
        "---",
        "",
    ]
    return "\n".join(lines) + content.strip()


def generate_worldbuilding_draft(project_dir: Path, brief: str = "", mock: bool = False) -> Path:
    apply_mock_env(mock)
    router = LLMRouter(project_dir=project_dir)
    template = load_text(project_dir / "prompts" / "世界观生成.md")
    user_prompt = render_template(
        template,
        {
            "brief": compact_planning_text(brief, _input_limit("brief"), "用户灵感"),
            "current_world": load_planning_text(project_dir / "00_世界观" / "世界观.md", "world", "当前世界观"),
            "style": load_planning_text(project_dir / "00_世界观" / "文风档案.md", "style", "文风档案"),
        },
    )
    user_prompt = add_project_linkage(project_dir, user_prompt, "world")
    content = router.assist_text(
        "你是长篇中文类型小说的世界观架构师，擅长把灵感整理成可执行设定。",
        user_prompt,
        workflow="assist_worldbuilding",
        role="director",
    )
    content = add_visible_linkage_header(project_dir, content, "world")
    return save_draft(project_dir, "00_世界观", "世界观草案", content)


def generate_outline_draft(project_dir: Path, brief: str = "", mock: bool = False) -> Path:
    apply_mock_env(mock)
    router = LLMRouter(project_dir=project_dir)
    template = load_text(project_dir / "prompts" / "总纲生成.md")
    user_prompt = render_template(
        template,
        {
            "brief": compact_planning_text(brief, _input_limit("brief"), "用户灵感"),
            "world": load_planning_text(project_dir / "00_世界观" / "世界观.md", "world", "世界观"),
            "current_outline": load_planning_text(project_dir / "01_大纲" / "总纲.md", "current_outline", "当前总纲"),
            "foreshadowing": load_planning_text(project_dir / "03_滚动记忆" / "伏笔追踪.md", "foreshadowing", "伏笔追踪"),
        },
    )
    user_prompt = add_project_linkage(project_dir, user_prompt, "outline")
    content = _assist_text_with_continuation(
        router,
        "你是长篇中文小说总策划，擅长设计主线、阶段目标和反转节奏。",
        user_prompt,
        workflow="assist_global_outline",
        role="director",
        max_tokens=_outline_output_max_tokens(router),
        end_marker=OUTLINE_END_MARKER,
        continuation_label="总纲草案",
    )
    content = add_visible_linkage_header(project_dir, content, "outline")
    return save_draft(project_dir, "01_大纲", "总纲草案", content)


def generate_volume_outline_draft(project_dir: Path, volume_name: str, brief: str = "", mock: bool = False) -> Path:
    apply_mock_env(mock)
    router = LLMRouter(project_dir=project_dir)
    volume_rel = _volume_outline_rel(volume_name)
    current_volume = load_planning_text(project_dir / volume_rel, "outline", f"{volume_name}当前卷纲")
    template = load_text(project_dir / "prompts" / "卷纲生成.md")
    if not template:
        template = (
            "# Prompt：卷纲辅助生成\n\n"
            "请基于项目轴、世界观、总纲、当前卷纲和用户补充灵感，生成本卷的卷/幕大纲草案。\n\n"
            "## 卷纲文件\n{{ volume_name }}\n\n"
            "## 用户补充灵感\n{{ brief }}\n\n"
            "## 世界观\n{{ world }}\n\n"
            "## 总纲\n{{ outline }}\n\n"
            "## 当前卷纲\n{{ current_volume }}\n\n"
            "## 输出要求\n"
            "- 使用 Markdown。\n"
            "- 开头必须包含“项目规格对齐”小节。\n"
            "- 保留并明确章节范围。\n"
            "- 包含：卷定位、核心冲突、角色弧线、伏笔预算、节奏目标、卷末状态。\n"
            "- 不要直接写正文。\n"
        )
    user_prompt = render_template(
        template,
        {
            "volume_name": volume_name,
            "brief": compact_planning_text(brief, _input_limit("brief"), "卷纲生成要求"),
            "world": load_planning_text(project_dir / "00_世界观" / "世界观.md", "world", "世界观"),
            "outline": load_planning_text(project_dir / "01_大纲" / "总纲.md", "outline", "总纲"),
            "current_volume": current_volume,
        },
    )
    user_prompt = add_project_linkage(project_dir, user_prompt, "outline")
    content = router.assist_text(
        "你是长篇中文小说卷/幕结构策划，擅长把总纲拆成可持续推进的阶段目标。",
        user_prompt,
        workflow="assist_volume_outline",
        role="director",
        max_tokens=_outline_output_max_tokens(router),
    )
    content = add_visible_linkage_header(project_dir, content, "volume")
    prefix = f"{Path(volume_name).stem}卷纲草案"
    return save_draft(project_dir, "01_大纲/卷纲", prefix, content)


def generate_character_draft(project_dir: Path, character_name: str, brief: str = "", mock: bool = False) -> Path:
    apply_mock_env(mock)
    router = LLMRouter(project_dir=project_dir)
    template = load_text(project_dir / "prompts" / "角色生成.md")
    user_prompt = render_template(
        template,
        {
            "character_name": character_name,
            "brief": compact_planning_text(brief, _input_limit("brief"), "角色灵感"),
            "world": load_planning_text(project_dir / "00_世界观" / "世界观.md", "world", "世界观"),
            "outline": load_planning_text(project_dir / "01_大纲" / "总纲.md", "outline", "总纲"),
            "template": load_planning_text(project_dir / "00_世界观" / "角色档案" / "角色模板.md", "template", "角色模板"),
        },
    )
    user_prompt = add_project_linkage(project_dir, user_prompt, "character")
    content = router.assist_text(
        "你是长篇中文小说人物设定编辑，擅长设计人物动机、弱点、声音和可持续弧线。",
        user_prompt,
        workflow="assist_character",
        role="director",
    )
    content = add_visible_linkage_header(project_dir, content, "character")
    path = save_draft(project_dir, "00_世界观/角色档案", f"{character_name or '角色'}草案", content)
    _supersede_same_target_drafts(project_dir, path)
    return path


def generate_character_batch_drafts(
    project_dir: Path,
    count: int = 6,
    brief: str = "",
    mock: bool = False,
) -> list[Path]:
    desired_count = max(1, min(int(count), 20))
    apply_mock_env(mock)
    router = LLMRouter(project_dir=project_dir)
    template = load_text(project_dir / "prompts" / "角色批量生成.md")
    user_prompt = render_template(
        template,
        {
            "count": str(desired_count),
            "brief": compact_planning_text(brief, _input_limit("brief"), "批量角色要求"),
            "world": load_planning_text(project_dir / "00_世界观" / "世界观.md", "world", "世界观"),
            "outline": load_planning_text(project_dir / "01_大纲" / "总纲.md", "outline", "总纲"),
            "existing_characters": compact_planning_text(existing_character_index(project_dir), _input_limit("characters"), "已有角色列表"),
            "template": load_planning_text(project_dir / "00_世界观" / "角色档案" / "角色模板.md", "template", "角色模板"),
        },
    )
    user_prompt = add_project_linkage(project_dir, user_prompt, "character_batch")
    content = router.assist_text(
        "你是长篇中文小说人物群像设计总监，擅长根据世界设定批量生成互相牵制的角色档案。",
        user_prompt,
        workflow="assist_character_batch",
        role="director",
        max_tokens=max(4000, min(30000, desired_count * 1800)),
    )
    linked_content = add_visible_linkage_header(project_dir, content, "character_batch")
    blocks = split_character_batch(linked_content)
    if len(blocks) < desired_count:
        blocks.extend(build_supplemental_character_blocks(project_dir, desired_count - len(blocks), [name for name, _ in blocks], brief))
    if not blocks:
        path = save_draft(project_dir, "00_世界观/角色档案", "批量角色草案", linked_content)
        _supersede_same_target_drafts(project_dir, path)
        return [path]
    header = add_visible_linkage_header(project_dir, "", "character_batch").strip()
    paths = []
    for name, block in blocks[:desired_count]:
        path = save_draft(project_dir, "00_世界观/角色档案", f"{safe_filename(name)}草案", f"{header}\n\n{block}")
        _supersede_same_target_drafts(project_dir, path)
        paths.append(path)
    return paths


def split_character_batch(content: str) -> list[tuple[str, str]]:
    pattern = re.compile(r"^(#{1,3})\s*(?:\d+[\.\、]\s*)?(?:角色档案|角色)[：:]\s*(.+?)\s*$", re.MULTILINE)
    starts = list(pattern.finditer(content))
    blocks: list[tuple[str, str]] = []
    for idx, match in enumerate(starts):
        start = match.start()
        end = starts[idx + 1].start() if idx + 1 < len(starts) else len(content)
        name = match.group(2).strip()
        block = content[start:end].strip()
        if name and block:
            lines = block.splitlines()
            lines[0] = f"# 角色档案：{name}"
            block = "\n".join(lines).strip()
            blocks.append((name, block))
    return blocks


def build_supplemental_character_blocks(
    project_dir: Path,
    missing_count: int,
    existing_names: list[str],
    brief: str = "",
) -> list[tuple[str, str]]:
    spec = parse_story_spec(project_dir)
    one_line = spec.get("一句话概括", "")
    genre = spec.get("类型与卖点", "")
    story_focus = one_line or brief or "当前长篇主线"
    role_slots = [
        ("推动者", "把主线事件真正推到台前，迫使主角行动。"),
        ("阻碍者", "代表旧秩序或现实压力，持续制造选择代价。"),
        ("信息持有者", "掌握关键线索，但不会一次性交出真相。"),
        ("情感牵引者", "让主角的目标和情感选择互相牵动。"),
        ("灰度盟友", "能提供帮助，也有自己的交换条件和秘密。"),
        ("镜像角色", "走过与主角相似但更危险的道路。"),
        ("压力测试者", "专门暴露主角计划中的漏洞。"),
        ("代价见证者", "承接主线选择带来的现实后果。"),
    ]
    seed_names = ["顾闻川", "许清棠", "周砚北", "姜照雪", "程以安", "陆明微", "韩序", "叶知遥", "沈归舟", "林见微"]
    used = set(existing_names)
    blocks: list[tuple[str, str]] = []
    for index in range(missing_count):
        role, duty = role_slots[(len(existing_names) + index) % len(role_slots)]
        name = next((candidate for candidate in seed_names if candidate not in used), f"补充角色{index + 1}")
        used.add(name)
        block = f"""# 角色档案：{name}

## 项目规格对齐
- 服务故事规格：{story_focus}
- 类型与卖点关联：{genre or "围绕主线冲突、人物关系和章节钩子推进。"}
- 群像职责：{role}，{duty}

## 基础信息
- 角色定位：{role}。
- 首次登场功能：在主角推进目标时带来新的资源、阻力或判断标准。

## 外貌不可变特征
- 有一个容易被读者记住的细节：说话前会先观察对方手上的动作。

## 核心驱动
- 外在目标：用自己的方式影响主线走向。
- 内在恐惧：害怕关键选择证明自己一直以来的坚持是错的。

## 恐惧
- 被迫承认自己依赖的人或制度并不可靠。

## 道德边界
- 可以隐瞒信息，但不主动伤害无辜者。

## 说话方式
- 先给事实，再给判断；情绪越强烈，句子越短。

## 绝不会说的话
- “这件事和我没有关系。”

## 标志性动作
- 遇到压力时会把视线移到出口或窗外。

## 秘密
- 曾经提前知道一条会影响主角选择的信息。

## 关系钩子
- 与主角既有合作价值，也会在关键节点提出相反选择。

## 当前状态
- 尚未完全站队，正在观察主角是否值得投入代价。
"""
        blocks.append((name, block))
    return blocks


# ─── AI 审查 / 改稿 ──────────────────────────────────────────────────────────

_REVIEW_FORMAT = """请按以下结构输出审查报告：

## 优势（保留）
（3-5 条具体优势，说明保留理由）

## 问题（需修正）
（按严重程度排列；每条：问题描述 → 具体修改建议）

## 缺失（需补充）
（叙事必要但尚未写入的内容）

## 优先改进行动
（最多 3 条，可立即执行的操作）
"""

_SYS_REVIEW_WORLD = "你是长篇中文类型小说的世界观评审编辑，从读者吸引力、内部逻辑一致性、角色制约性和情节支撑度四个维度审查设定，给出结构化、可操作的反馈。"
_SYS_REVIEW_CHAR = "你是长篇中文小说人物编辑，从动机可信度、弧线完整性、独特性和与主线联动四个维度审查角色档案，给出结构化、可操作的反馈。"
_SYS_REVIEW_OUTLINE = "你是长篇中文小说结构编辑，从故事弧度、节奏分配、冲突密度和读者钩子四个维度审查大纲，给出结构化、可操作的反馈。"
_SYS_REVIEW_VOLUME = "你是长篇中文小说卷/幕结构编辑，从阶段目标、冲突升级、伏笔预算、卷末状态和总纲承接五个维度审查卷纲，给出结构化、可操作的反馈。"
_SYS_REVIEW_CHAPTER = "你是长篇中文小说章节策划编辑，从场景节奏、冲突推进、钩子效果和与整体弧度的衔接四个维度审查章纲，给出结构化、可操作的反馈。"

_SYS_IMPROVE_WORLD = "你是长篇中文类型小说世界观架构师，根据编辑反馈改进设定文档，使其更完整、一致、对情节有实质支撑，输出完整改进版文档。"
_SYS_IMPROVE_CHAR = "你是长篇中文小说人物设定编辑，根据编辑反馈改进角色档案，输出完整改进版文档。"
_SYS_IMPROVE_OUTLINE = "你是长篇中文小说总策划，根据编辑反馈改进总纲，保留优势、修正问题、补充缺失，输出完整改进版总纲。"
_SYS_IMPROVE_VOLUME = "你是长篇中文小说卷/幕结构策划，根据编辑反馈改进卷纲，保留总纲承接关系，补齐阶段目标、伏笔预算和卷末状态，输出完整改进版卷纲。"
_SYS_IMPROVE_CHAPTER = "你是长篇中文小说章节策划，根据编辑反馈改进章纲，输出完整改进版章纲文档。"


def _review_with_local_consistency(project_dir: Path, result: str) -> str:
    consistency = render_story_consistency_review(project_dir)
    return f"{consistency}\n\n---\n\n{result}" if consistency else result


def review_worldbuilding(project_dir: Path, mock: bool = False) -> str:
    apply_mock_env(mock)
    router = LLMRouter(project_dir=project_dir)
    content = load_text(project_dir / "00_世界观" / "世界观.md")
    if not content.strip():
        return "世界观文档为空，无法审查。请先填写内容。"
    spec = spec_summary_block(parse_story_spec(project_dir))
    outline = load_planning_text(project_dir / "01_大纲" / "总纲.md", "outline", "总纲")
    prompt = (
        f"{_REVIEW_FORMAT}\n\n"
        f"{_consistency_context(project_dir)}\n\n"
        f"**世界观设定：**\n{compact_planning_text(content, _input_limit('world'), '世界观设定')}\n\n"
        f"**故事规格摘要：**\n{spec or '（未填写）'}\n\n"
        f"**总纲摘要：**\n{outline if outline else '（未填写）'}"
    )
    prompt = add_project_linkage(project_dir, prompt, "world")
    result = router.critic_text(_SYS_REVIEW_WORLD, prompt, workflow="review_world", role="critic")
    return _review_with_local_consistency(project_dir, result)


def improve_worldbuilding(project_dir: Path, review_text: str, mock: bool = False) -> Path:
    apply_mock_env(mock)
    router = LLMRouter(project_dir=project_dir)
    content = load_text(project_dir / "00_世界观" / "世界观.md")
    prompt = (
        f"根据以下审查意见改进世界观设定，保留优势、修正问题、补充缺失，输出完整改进版文档。\n\n"
        f"**本地一致性预警：**\n{_consistency_context(project_dir)}\n\n"
        f"**审查意见：**\n{compact_planning_text(review_text, _input_limit('review'), '世界观审查意见')}\n\n"
        f"**当前世界观：**\n{compact_planning_text(content, _input_limit('world'), '当前世界观')}"
    )
    result = router.revise_text(_SYS_IMPROVE_WORLD, add_project_linkage(project_dir, prompt, "world"), workflow="improve_world", role="reviser")
    result = add_visible_linkage_header(project_dir, result, "world")
    return save_draft(project_dir, "00_世界观", "世界观改稿", result)


def review_character(project_dir: Path, character_rel: str, mock: bool = False) -> str:
    apply_mock_env(mock)
    router = LLMRouter(project_dir=project_dir)
    content = load_text(project_dir / character_rel)
    if not content.strip():
        return "角色档案为空，无法审查。"
    spec = spec_summary_block(parse_story_spec(project_dir))
    outline = load_planning_text(project_dir / "01_大纲" / "总纲.md", "outline", "总纲")
    others = compact_planning_text(existing_character_index(project_dir), _input_limit("characters"), "已有角色列表")
    prompt = (
        f"{_REVIEW_FORMAT}\n\n"
        f"{_consistency_context(project_dir)}\n\n"
        f"**角色档案：**\n{compact_planning_text(content, _input_limit('character'), '角色档案')}\n\n"
        f"**故事规格：**\n{spec or '（未填写）'}\n\n"
        f"**总纲摘要：**\n{outline if outline else '（未填写）'}\n\n"
        f"**已有角色列表：**\n{others}"
    )
    prompt = add_project_linkage(project_dir, prompt, "character")
    result = router.critic_text(_SYS_REVIEW_CHAR, prompt, workflow="review_character", role="critic")
    return _review_with_local_consistency(project_dir, result)


def improve_character(project_dir: Path, character_rel: str, review_text: str, mock: bool = False) -> Path:
    apply_mock_env(mock)
    router = LLMRouter(project_dir=project_dir)
    content = load_text(project_dir / character_rel)
    char_name = Path(character_rel).stem
    prompt = (
        f"根据以下审查意见改进角色档案，保留优势、修正问题、补充缺失，输出完整改进版档案。\n\n"
        f"**本地一致性预警：**\n{_consistency_context(project_dir)}\n\n"
        f"**审查意见：**\n{compact_planning_text(review_text, _input_limit('review'), '角色审查意见')}\n\n"
        f"**当前角色档案（{char_name}）：**\n{compact_planning_text(content, _input_limit('character'), '当前角色档案')}"
    )
    result = router.revise_text(_SYS_IMPROVE_CHAR, add_project_linkage(project_dir, prompt, "character"), workflow="improve_character", role="reviser")
    result = add_visible_linkage_header(project_dir, result, "character")
    path = save_draft(project_dir, "00_世界观/角色档案", f"{char_name}改稿", result)
    _supersede_same_target_drafts(project_dir, path)
    return path


def review_global_outline(project_dir: Path, mock: bool = False) -> str:
    apply_mock_env(mock)
    router = LLMRouter(project_dir=project_dir)
    content = load_text(project_dir / "01_大纲" / "总纲.md")
    if not content.strip():
        return "总纲为空，无法审查。请先填写总纲内容。"
    spec = spec_summary_block(parse_story_spec(project_dir))
    world = load_planning_text(project_dir / "00_世界观" / "世界观.md", "world", "世界观")
    prompt = (
        f"{_REVIEW_FORMAT}\n\n"
        f"{_consistency_context(project_dir)}\n\n"
        f"**总纲：**\n{compact_planning_text(content, _input_limit('outline'), '总纲')}\n\n"
        f"**故事规格：**\n{spec or '（未填写）'}\n\n"
        f"**世界观摘要：**\n{world if world else '（未填写）'}"
    )
    prompt = add_project_linkage(project_dir, prompt, "outline")
    result = router.critic_text(_SYS_REVIEW_OUTLINE, prompt, workflow="review_outline", role="critic")
    return _review_with_local_consistency(project_dir, result)


def improve_global_outline(project_dir: Path, review_text: str, mock: bool = False) -> Path:
    apply_mock_env(mock)
    router = LLMRouter(project_dir=project_dir)
    content = load_text(project_dir / "01_大纲" / "总纲.md")
    prompt = (
        f"根据以下审查意见改进总纲，保留优势、修正问题、补充缺失，输出完整改进版总纲。\n\n"
        f"**本地一致性预警：**\n{_consistency_context(project_dir)}\n\n"
        f"**审查意见：**\n{compact_planning_text(review_text, _input_limit('review'), '总纲审查意见')}\n\n"
        f"**当前总纲：**\n{compact_planning_text(content, _input_limit('outline'), '当前总纲')}"
    )
    result = _revise_outline_with_continuation(
        router,
        _SYS_IMPROVE_OUTLINE,
        add_project_linkage(project_dir, prompt, "outline"),
        workflow="improve_outline",
    )
    result = add_visible_linkage_header(project_dir, result, "outline")
    return save_draft(project_dir, "01_大纲", "总纲改稿", result)


def review_volume_outline(project_dir: Path, volume_name: str, mock: bool = False) -> str:
    apply_mock_env(mock)
    router = LLMRouter(project_dir=project_dir)
    volume_rel = _volume_outline_rel(volume_name)
    content = load_text(project_dir / volume_rel)
    if not content.strip():
        return f"{volume_name} 卷纲为空，无法审查。"
    spec = spec_summary_block(parse_story_spec(project_dir))
    outline = load_planning_text(project_dir / "01_大纲" / "总纲.md", "outline", "总纲")
    prompt = (
        f"{_REVIEW_FORMAT}\n\n"
        f"{_consistency_context(project_dir)}\n\n"
        f"**卷纲文件：**\n{volume_name}\n\n"
        f"**卷纲：**\n{compact_planning_text(content, _input_limit('outline'), f'{volume_name}卷纲')}\n\n"
        f"**故事规格：**\n{spec or '（未填写）'}\n\n"
        f"**总纲节选：**\n{outline if outline else '（未填写）'}"
    )
    prompt = add_project_linkage(project_dir, prompt, "outline")
    result = router.critic_text(_SYS_REVIEW_VOLUME, prompt, workflow="review_volume_outline", role="critic")
    return _review_with_local_consistency(project_dir, result)


def improve_volume_outline(project_dir: Path, volume_name: str, review_text: str, mock: bool = False) -> Path:
    apply_mock_env(mock)
    router = LLMRouter(project_dir=project_dir)
    volume_rel = _volume_outline_rel(volume_name)
    content = load_text(project_dir / volume_rel)
    prompt = (
        f"根据以下审查意见改进 {volume_name} 卷纲，保留优势、修正问题，输出完整改进版卷纲。\n\n"
        f"**本地一致性预警：**\n{_consistency_context(project_dir)}\n\n"
        f"**审查意见：**\n{compact_planning_text(review_text, _input_limit('review'), f'{volume_name}审查意见')}\n\n"
        f"**当前卷纲：**\n{compact_planning_text(content, _input_limit('outline'), f'{volume_name}当前卷纲')}"
    )
    result = router.revise_text(
        _SYS_IMPROVE_VOLUME,
        add_project_linkage(project_dir, prompt, "outline"),
        workflow="improve_volume_outline",
        role="reviser",
        max_tokens=_outline_output_max_tokens(router),
    )
    result = add_visible_linkage_header(project_dir, result, "volume")
    return save_draft(project_dir, "01_大纲/卷纲", f"{Path(volume_name).stem}卷纲改稿", result)


def review_chapter_outline(project_dir: Path, chapter_num: int, mock: bool = False) -> str:
    apply_mock_env(mock)
    router = LLMRouter(project_dir=project_dir)
    ch = f"{chapter_num:03d}"
    content = load_text(project_dir / "01_大纲" / "章纲" / f"第{ch}章.md")
    if not content.strip():
        return f"第{ch}章章纲为空，无法审查。"
    outline = load_planning_text(project_dir / "01_大纲" / "总纲.md", "outline", "总纲")
    recent = load_planning_text(project_dir / "03_滚动记忆" / "最近摘要.md", "recent_summary", "最近进度摘要")
    prev_ch = f"{chapter_num - 1:03d}"
    prev = load_planning_text(project_dir / "01_大纲" / "章纲" / f"第{prev_ch}章.md", "chapter_outline", f"第{prev_ch}章章纲") if chapter_num > 1 else ""
    next_ch = f"{chapter_num + 1:03d}"
    next_c = load_planning_text(project_dir / "01_大纲" / "章纲" / f"第{next_ch}章.md", "chapter_outline", f"第{next_ch}章章纲")
    context_block = ""
    if prev:
        context_block += f"**上一章（第{prev_ch}章）章纲摘要：**\n{prev}\n\n"
    if next_c:
        context_block += f"**下一章（第{next_ch}章）章纲：**\n{next_c}\n\n"
    prompt = (
        f"{_REVIEW_FORMAT}\n\n"
        f"**第{ch}章章纲：**\n{compact_planning_text(content, _input_limit('chapter_outline'), f'第{ch}章章纲')}\n\n"
        f"**总纲节选：**\n{outline if outline else '（未填写）'}\n\n"
        f"{context_block}"
        f"**最近进度摘要：**\n{recent if recent else '（无）'}"
    )
    prompt = add_project_linkage(project_dir, prompt, "chapter")
    return router.critic_text(_SYS_REVIEW_CHAPTER, prompt, workflow="review_chapter_outline", role="critic")


def improve_chapter_outline(project_dir: Path, chapter_num: int, review_text: str, mock: bool = False) -> Path:
    apply_mock_env(mock)
    router = LLMRouter(project_dir=project_dir)
    ch = f"{chapter_num:03d}"
    content = load_text(project_dir / "01_大纲" / "章纲" / f"第{ch}章.md")
    prompt = (
        f"根据以下审查意见改进第{ch}章章纲，保留优势、修正问题，输出完整改进版章纲。\n\n"
        f"**审查意见：**\n{compact_planning_text(review_text, _input_limit('review'), f'第{ch}章审查意见')}\n\n"
        f"**当前章纲：**\n{compact_planning_text(content, _input_limit('chapter_outline'), f'第{ch}章当前章纲')}"
    )
    result = router.revise_text(_SYS_IMPROVE_CHAPTER, add_project_linkage(project_dir, prompt, "chapter"), workflow="improve_chapter_outline", role="reviser")
    result = add_visible_linkage_header(project_dir, result, "chapter")
    return save_draft(project_dir, "01_大纲/章纲", f"第{ch}章章纲改稿", result)


def _supersede_same_target_drafts(project_dir: Path, new_draft_path: Path) -> list[Path]:
    """Archive any pending drafts in the same AI草案 folder that map to the same adoption target."""
    from onboarding import infer_adoption_target
    try:
        new_target = infer_adoption_target(project_dir, new_draft_path)
    except Exception:
        return []
    draft_dir = new_draft_path.parent
    superseded: list[Path] = []
    for existing in sorted(draft_dir.glob("*.md")):
        if existing == new_draft_path or not existing.is_file():
            continue
        try:
            if infer_adoption_target(project_dir, existing) == new_target:
                archive_dir = draft_dir / "已采纳"
                archive_dir.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                archived = unique_path(archive_dir / f"{existing.stem}_superseded_{stamp}{existing.suffix}")
                shutil.move(str(existing), archived)
                superseded.append(existing)
        except Exception:
            continue
    return superseded


def existing_character_index(project_dir: Path) -> str:
    char_dir = project_dir / "00_世界观" / "角色档案"
    if not char_dir.exists():
        return "暂无"
    names = [
        path.stem
        for path in sorted(char_dir.glob("*.md"))
        if path.name != "角色模板.md" and not _looks_like_non_character_profile(path)
    ]
    return "、".join(names) if names else "暂无"


def _looks_like_non_character_profile(path: Path) -> bool:
    stem = path.stem.strip()
    if stem.startswith("#") or "项目规格对齐" in stem:
        return True
    return False


def _volume_outline_rel(volume_name: str) -> str:
    name = Path(str(volume_name or "")).name
    if not name:
        name = "第01卷.md"
    if not name.endswith(".md"):
        name = f"{name}.md"
    return f"01_大纲/卷纲/{name}"


def generate_chapter_outline_draft(project_dir: Path, chapter_num: int, brief: str = "", mock: bool = False) -> Path:
    apply_mock_env(mock)
    router = LLMRouter(project_dir=project_dir)
    template = load_text(project_dir / "prompts" / "章纲生成.md")
    current_chapter = load_planning_text(
        project_dir / "01_大纲" / "章纲" / f"第{chapter_num:03d}章.md",
        "chapter_outline",
        f"第{chapter_num:03d}章当前章纲",
    )
    user_prompt = render_template(
        template,
        {
            "chapter_num": f"{chapter_num:03d}",
            "brief": compact_planning_text(brief, _input_limit("brief"), "章纲生成要求"),
            "world": load_planning_text(project_dir / "00_世界观" / "世界观.md", "world", "世界观"),
            "outline": load_planning_text(project_dir / "01_大纲" / "总纲.md", "outline", "总纲"),
            "recent_summary": load_planning_text(project_dir / "03_滚动记忆" / "最近摘要.md", "recent_summary", "最近摘要"),
            "foreshadowing": load_planning_text(project_dir / "03_滚动记忆" / "伏笔追踪.md", "foreshadowing", "伏笔追踪"),
            "current_chapter_outline": current_chapter,
        },
    )
    user_prompt = add_project_linkage(project_dir, user_prompt, "chapter")
    content = router.assist_text(
        "你是长篇中文小说章节策划，擅长把总纲拆成可写、可审、可追踪的章纲。",
        user_prompt,
        workflow="assist_chapter_outline",
        role="director",
    )
    content = add_visible_linkage_header(project_dir, content, "chapter")
    return save_draft(project_dir, "01_大纲/章纲", f"第{chapter_num:03d}章章纲草案", content)
