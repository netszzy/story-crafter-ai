"""
组装 LLM 调用所需的 system prompt 与 user-facing context。

V1.3 之前的章节生成路径只把"滚动记忆 + RAG 召回"喂给模型，
项目宪法、故事规格、文风档案、总纲、任务卡都没进 LLM。本模块把这些
顶层约束统一注入，让 CLI 与 WebUI 走同一套装配逻辑。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from style_profiles import (
    get_style_profile,
    profile_sample_path,
    render_style_profile_block,
    resolve_style_profile_name,
)


CONSTITUTION_REL = "05_项目管理/创作宪法.md"
SPEC_REL = "05_项目管理/故事规格.md"
STYLE_REL = "00_世界观/文风档案.md"
GLOBAL_OUTLINE_REL = "01_大纲/总纲.md"
VOLUME_DIR_REL = "01_大纲/卷纲"
PROSE_TEMPLATE_REL = "prompts/正文生成.md"
STYLE_SEED_REL = "prompts/style_seed_library.md"

GLOBAL_SUMMARY_REL = "03_滚动记忆/全局摘要.md"
RECENT_SUMMARY_REL = "03_滚动记忆/最近摘要.md"
FORESHADOW_REL = "03_滚动记忆/伏笔追踪.md"
CHARACTER_STATE_REL = "03_滚动记忆/人物状态表.md"
WORLD_REL = "00_世界观/世界观.md"
CHARACTER_DIR_REL = "00_世界观/角色档案"


AXIS_LIMITS = {
    "constitution": 1500,
    "style": 2000,
    "outline": 2500,
    "volume": 3500,
    "consistency": 2200,
}

ROLLING_LIMITS = {
    "global_summary": 3000,
    "recent_summary": 4000,
    "foreshadow": 3000,
    "character_state": 2500,
}

PLANNING_LIMITS = {
    "world": 2500,
    "characters": 2500,
}


# ---------------------------------------------------------------------------
# Story spec parsing
# ---------------------------------------------------------------------------


SPEC_SECTION_PATTERN = re.compile(r"^##\s+\d+\.\s+(.+?)\s*$", re.MULTILINE)
ANSWER_PATTERN = re.compile(r"\*\*回答\*\*[：:]?\s*([\s\S]*)", re.MULTILINE)
PLACEHOLDER_TOKENS = ("待补充", "在此填写", "请替换", "此处为空")


def parse_story_spec(project_dir: Path) -> dict[str, str]:
    """从故事规格 markdown 抽取六节的"**回答**："内容。

    所有"（请在此填写）"占位会被剔除；若一节仍只剩占位文本，对应字段返回空串。
    """
    path = project_dir / SPEC_REL
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8")
    sections = _split_sections(text)
    return {
        "logline": _extract_answer(sections.get("一句话概括", "")),
        "audience": _extract_answer(sections.get("目标读者", "")),
        "core_conflict": _extract_answer(sections.get("核心冲突", "")),
        "main_characters": _extract_answer(sections.get("主要角色", "")),
        "selling_points": _extract_answer(sections.get("类型与卖点", "")),
        "success_criteria": _extract_answer(sections.get("成功标准", "")),
    }


def spec_summary_block(spec: dict[str, str]) -> str:
    """把解析后的规格压缩成简短摘要，给 axis context 用。"""
    if not any(spec.values()):
        return ""
    lines: list[str] = []
    if spec.get("logline"):
        lines.append(f"- 一句话：{_oneline(spec['logline'], 200)}")
    if spec.get("audience"):
        lines.append(f"- 目标读者：{_oneline(spec['audience'], 200)}")
    if spec.get("core_conflict"):
        lines.append(f"- 核心冲突：{_oneline(spec['core_conflict'], 220)}")
    if spec.get("main_characters"):
        lines.append(f"- 主要角色：{_oneline(spec['main_characters'], 280)}")
    if spec.get("selling_points"):
        lines.append(f"- 类型与卖点：{_oneline(spec['selling_points'], 220)}")
    if spec.get("success_criteria"):
        lines.append(f"- 成功标准：{_oneline(spec['success_criteria'], 200)}")
    return "\n".join(lines)


def derive_genre_hint(spec: dict[str, str]) -> str:
    """从"类型与卖点"里抽出"类型："那一行作为 system prompt 的类型描述。"""
    selling = spec.get("selling_points", "")
    for line in selling.splitlines():
        stripped = line.strip("- ·").strip()
        if stripped.startswith("类型"):
            _, sep, val = stripped.partition("：")
            if not sep:
                _, _, val = stripped.partition(":")
            cleaned = val.strip()
            if cleaned:
                return cleaned
    return _oneline(selling, 80) if selling else ""


def derive_audience_hint(spec: dict[str, str]) -> str:
    return _oneline(spec.get("audience", ""), 120)


# ---------------------------------------------------------------------------
# System prompt rendering
# ---------------------------------------------------------------------------


def render_prose_system_prompt(project_dir: Path, current_chapter_num: int = 1) -> str:
    """读取 prose 模板，用故事规格、宪法、文风档案渲染。"""
    template_path = project_dir / PROSE_TEMPLATE_REL
    template = template_path.read_text(encoding="utf-8") if template_path.exists() else ""
    spec = parse_story_spec(project_dir)
    constitution = _read_capped(project_dir / CONSTITUTION_REL, AXIS_LIMITS["constitution"])
    style = _read_capped(project_dir / STYLE_REL, AXIS_LIMITS["style"])
    style_profile_name = resolve_style_profile_name(project_dir, current_chapter_num)

    values = {
        "genre_hint": derive_genre_hint(spec) or "通用中文小说",
        "audience_hint": derive_audience_hint(spec) or "成熟中文读者",
        "core_conflict": spec.get("core_conflict") or "（项目尚未填写核心冲突，请按章纲与角色档案推断）",
        "selling_points": spec.get("selling_points") or "（项目尚未填写类型与卖点）",
        "style_rules": style or "（项目尚未填写文风档案，按通用写作规则执行）",
        "style_profile": render_style_profile_block(project_dir, style_profile_name)
        or "（本章未指定项目风格档案，按文风档案与任务卡执行）",
        "chapter_mode_rules": render_chapter_mode_rules(project_dir, current_chapter_num),
        "style_samples": inject_prose_samples(project_dir, current_chapter_num, style_profile_name=style_profile_name)
        or "（项目暂未提供具体文风样本，请以文风档案规则为准）",
        "constitution": constitution or "（项目宪法尚未填写）",
    }
    result = _render_template(template, values).strip() + "\n"
    # V4.0 Phase B: 注入上一章声音诊断
    voice_hints = inject_voice_hints(project_dir, current_chapter_num)
    if voice_hints:
        result += "\n" + voice_hints
    # V4.0 Phase C: 注入技巧焦点指令
    technique_block = render_technique_enforcement(project_dir, current_chapter_num)
    if technique_block:
        result += "\n" + technique_block
    return result


def inject_voice_hints(project_dir: Path, current_chapter_num: int) -> str:
    """从上一章的声音诊断读取角色声音区分提示，注入正文生成 prompt。"""
    prev_chapter = current_chapter_num - 1
    if prev_chapter < 1:
        return ""
    json_path = project_dir / "04_审核日志" / f"第{prev_chapter:03d}章_声音诊断.json"
    if not json_path.exists():
        return ""
    try:
        from novel_schemas import VoiceFingerprint
        data = json.loads(json_path.read_text(encoding="utf-8"))
        fp = VoiceFingerprint.model_validate(data)
        from voice_diagnostics import voice_fingerprint_to_prose_hints
        return voice_fingerprint_to_prose_hints(fp)
    except Exception:
        return ""


def inject_prose_samples(
    project_dir: Path,
    current_chapter_num: int,
    max_samples: int = 3,
    style_profile_name: str | None = None,
) -> str:
    picked: list[tuple[str, str, str]] = []
    seen: set[str] = set()

    def add(source: str, technique: str, passage: str) -> None:
        if len(picked) >= max_samples:
            return
        normalized = _normalize_sample_text(passage)
        if not normalized or normalized in seen:
            return
        normalized = _clip_sample_text(normalized)
        seen.add(normalized)
        picked.append((source, _short_sample_label(technique), normalized))

    for technique, passage in _load_user_style_samples(project_dir):
        add("文风档案", technique, passage)

    # V3.1：从持久化样本池选取（锁定条目优先）
    if len(picked) < max_samples:
        try:
            from sample_pool import get_pool_samples, load_pool
            pool = load_pool(project_dir)
            for source, technique, passage in get_pool_samples(pool, max_samples - len(picked), seen):
                add(source, technique, passage)
        except Exception:
            pass

    # 兜底：扫描已定稿章节
    if len(picked) < max_samples:
        for technique, passage in _sample_from_finalized_chapters(project_dir, current_chapter_num, max_samples - len(picked)):
            add("已定稿章节", technique, passage)
    if len(picked) < max_samples and style_profile_name:
        profile = get_style_profile(style_profile_name, project_dir=project_dir)
        source = profile.display_name if profile else "风格档案"
        for technique, passage in _load_profile_seed_library(project_dir, style_profile_name):
            add(source, technique, passage)
    if len(picked) < max_samples:
        for technique, passage in _load_seed_library(project_dir):
            add("种子库", technique, passage)

    lines = []
    for index, (source, technique, passage) in enumerate(picked, start=1):
        lines.append(f"样本 {index}（来自{source}·技巧：{technique}）：\n>>> {passage}")
    return "\n\n".join(lines)


def render_chapter_mode_rules(project_dir: Path, chapter_num: int) -> str:
    try:
        from structured_store import read_task_card

        card = read_task_card(project_dir, chapter_num)
    except Exception:
        card = None
    mode = getattr(card, "chapter_mode", "plot") if card else "plot"
    pacing = getattr(card, "pacing", "normal") if card else "normal"
    ending_style = getattr(card, "ending_style", "hook") if card else "hook"
    mode_rules = {
        "plot": "剧情推进章：阻力、选择、代价必须可见；章末需要明确 hook。",
        "bridge": "过渡桥接章：允许节奏放缓，但必须交代关系变化、信息换挡或下一阶段入口。",
        "interior": "内省章：允许低冲突和低对白，用自我欺骗、沉默、物件和动作写心理，不强行补外部对抗。",
        "atmosphere": "氛围章：以场景质地、异常物件和未说之语建立压力，冲突可潜伏在环境和细节里。",
        "epilogue": "尾声章：余韵优先，收束人物后果，留下回声而不是硬反转。",
    }
    ending_rules = {
        "hook": "结尾方式：留出下一章追问点。",
        "cliffhanger": "结尾方式：把危险、反转或决定压在最后一拍。",
        "open": "结尾方式：允许开放式余味，不必解释完答案。",
        "echo": "结尾方式：用前文物件、句子或动作形成回声。",
    }
    return "\n".join([
        "## 本章模式写作规则",
        f"- ChapterMode：{mode}。{mode_rules.get(mode, mode_rules['plot'])}",
        f"- pacing：{pacing}。",
        f"- ending_style：{ending_style}。{ending_rules.get(ending_style, ending_rules['hook'])}",
        "- 若本章为 interior/atmosphere/slow_burn，不要为了迎合通用指标强行增加打斗、争吵或身体情绪直写。",
    ])


# ── V4.0 Phase C 技巧驱动生成 ────────────────────────────────────────────────


def render_technique_enforcement(project_dir: Path, chapter_num: int) -> str:
    """读取任务卡的 technique_focus，生成写作技巧强制指令。"""
    try:
        from structured_store import read_task_card
        card = read_task_card(project_dir, chapter_num)
        if not card or not card.technique_focus:
            return ""
        tips = _technique_tips_library()
        lines = ["## 本章必须使用的写作技巧", ""]
        for tech in card.technique_focus:
            tip = tips.get(tech, tech)
            lines.append(f"- {tech}：{tip}")
        return "\n".join(lines).strip()
    except Exception:
        return ""


def scene_type_techniques(scene_type: str) -> list[str]:
    """根据场景类型返回推荐技巧列表。"""
    mapping = {
        "开场": ["短句冲击", "感官锚点"],
        "对峙": ["潜台词", "身体反应替代副词"],
        "情感": ["身体化情感", "留白"],
        "动作": ["连续动作链", "短句冲击"],
        "揭示": ["信息折叠", "潜台词"],
        "过渡": ["环境拟人", "感官锚点"],
        "高潮": ["短句冲击", "连续动作链", "身体化情感"],
        "尾声": ["留白", "环境拟人"],
    }
    return mapping.get(scene_type, ["感官锚点", "身体反应替代副词"])


def _technique_tips_library() -> dict[str, str]:
    return {
        "短句冲击": "场景核心句不超过15字；关键动作以3-7字短句独立成段，制造急促节奏。",
        "感官锚点": "每场景至少2种感官细节（视觉/听觉/触觉/嗅觉），忌纯心理叙述。",
        "潜台词": "对白表面意思与真实意图错开；角色不说出真正的诉求，用动作或环境泄露。",
        "身体反应替代副词": "不用「紧张地说」「愤怒地喊」，写心跳、出汗、握拳、声线变化。",
        "身体化情感": "不写「他很悲伤」，写身体反应：嗓子发紧、眼眶发酸、手指发抖。",
        "连续动作链": "3个以上的连续具体动作（不超过12字/动作），不给抽象评价插入空间。",
        "留白": "段落末尾留1-2句未说完的话或未完成的动作，让读者自行补全情绪。",
        "信息折叠": "新信息不做纯说明段落，拆成冲突中的碎片，让读者拼图。",
        "环境拟人": "环境反射角色心理状态（如焦虑→雨声刺耳、风像推搡），而不是直接写情绪。",
    }


def _load_seed_library(project_dir: Path) -> list[tuple[str, str]]:
    """读取内置中文写作技巧段落库。"""
    path = project_dir / STYLE_SEED_REL
    if not path.exists():
        path = Path(__file__).resolve().parent / STYLE_SEED_REL
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    return _parse_labeled_sample_blocks(text)


def _load_profile_seed_library(project_dir: Path, profile_name: str | None) -> list[tuple[str, str]]:
    path = profile_sample_path(project_dir, profile_name)
    if path is None:
        return []
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    return _parse_labeled_sample_blocks(text)


def _load_user_style_samples(project_dir: Path) -> list[tuple[str, str]]:
    """读取文风档案里的用户示范段落。"""
    path = project_dir / STYLE_REL
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if not text:
        return []

    samples: list[tuple[str, str]] = []
    ref_pattern = re.compile(
        r"##\s*(?:参考|示范)段落\s*\S*[^\n]*\n\s*```\s*\n(.*?)```\s*\n(?:\*\*我喜欢这里的\*\*[：:]\s*(.*?))?(?=\n##\s*(?:参考|示范)段落|\n---|\Z)",
        re.DOTALL,
    )
    for match in ref_pattern.finditer(text):
        passage = match.group(1).strip()
        analysis = " ".join((match.group(2) or "").split())
        samples.append((analysis[:30] or "用户示范段落", passage))
    if samples:
        return samples

    section_match = re.search(r"(?ms)^##\s*示范段落[^\n]*\n(.*?)(?=^##\s+|\Z)", text)
    if section_match:
        for paragraph in _split_paragraphs(section_match.group(1)):
            samples.append(("用户示范段落", paragraph))
    return samples


def _sample_from_finalized_chapters(
    project_dir: Path,
    current_chapter_num: int,
    n: int,
) -> list[tuple[str, str]]:
    """从当前章之前的定稿章节抽取正文片段。"""
    if n <= 0 or current_chapter_num < 3:
        return []
    candidates: list[tuple[int, int, int, str]] = []
    body_dir = project_dir / "02_正文"
    for path in sorted(body_dir.glob("第*章_定稿.md")):
        match = re.search(r"第0*(\d+)章_定稿\.md$", path.name)
        if not match:
            continue
        chapter_num = int(match.group(1))
        if chapter_num >= current_chapter_num:
            continue
        score, is_mock = _read_dramatic_sample_meta(project_dir, chapter_num)
        if is_mock:
            continue
        if current_chapter_num >= 6 and (score is None or score < 80):
            continue
        text = path.read_text(encoding="utf-8")
        for idx, paragraph in enumerate(_candidate_paragraphs(text)[:3]):
            candidates.append((score if score is not None else 0, chapter_num, idx, paragraph))

    candidates.sort(key=lambda item: (-item[0], -item[1], item[2]))
    result = []
    for score, chapter_num, _, paragraph in candidates[:n]:
        label = f"第{chapter_num:03d}章高画面感片段" if score else f"第{chapter_num:03d}章定稿片段"
        result.append((label, paragraph))
    return result


def _extract_style_samples(style_text: str) -> str:
    """兼容旧接口：从给定文风文本中提取用户参考段落。"""
    samples = []
    ref_pattern = re.compile(
        r"## 参考段落\s*\S+\s*\n\s*```\s*\n(.*?)```\s*\n\*\*我喜欢这里的\*\*[：:]\s*(.*?)(?=\n## 参考段落|\n---|\Z)",
        re.DOTALL,
    )
    for match in ref_pattern.finditer(style_text or ""):
        passage = _normalize_sample_text(match.group(1))
        analysis = " ".join(match.group(2).split())
        if passage:
            samples.append(f"【样本】{passage}\n【风格要点】{analysis}")
    return "\n\n".join(samples)


def _parse_labeled_sample_blocks(text: str) -> list[tuple[str, str]]:
    pattern = re.compile(r"(?ms)^##\s*样本\s*\d+\s*[（(]技巧[：:](.*?)[）)]\s*\n(.*?)(?=^##\s*样本\s*\d+|\Z)")
    samples = []
    for match in pattern.finditer(text):
        technique = " ".join(match.group(1).split())
        passage = _normalize_sample_text(match.group(2))
        if passage:
            samples.append((technique, passage))
    return samples


def _candidate_paragraphs(text: str) -> list[str]:
    paragraphs = []
    for paragraph in _split_paragraphs(text):
        if paragraph.startswith("#"):
            continue
        length = len(re.sub(r"\s+", "", paragraph))
        if length < 80 or length > 220:
            continue
        if not _has_dialogue_or_action(paragraph):
            continue
        paragraphs.append(paragraph)
    return paragraphs


def _split_paragraphs(text: str) -> list[str]:
    blocks = re.split(r"\n\s*\n+", text.strip())
    if len(blocks) <= 1:
        blocks = text.splitlines()
    return [_normalize_sample_text(block) for block in blocks if _normalize_sample_text(block)]


def _has_dialogue_or_action(text: str) -> bool:
    if re.search(r"[“”\"「」『』]", text):
        return True
    return bool(re.search(r"(推|按|拿|放|走|停|看|抬|低|转|握|敲|递|靠|坐|站|笑|咬|摸|拧|摁|拉|关|开|躲|追|退|伸|拍|擦)", text))


def _read_dramatic_sample_meta(project_dir: Path, chapter_num: int) -> tuple[int | None, bool]:
    path = project_dir / "04_审核日志" / f"第{chapter_num:03d}章_戏剧诊断.json"
    if not path.exists():
        return None, False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, False
    score = data.get("cinematic_score")
    return (int(score) if isinstance(score, int) else None), bool(data.get("is_mock"))


def _normalize_sample_text(text: str) -> str:
    return " ".join(line.strip() for line in (text or "").splitlines() if line.strip())


def _clip_sample_text(text: str, limit: int = 220) -> str:
    return text if len(text) <= limit else text[:limit].rstrip() + "…"


def _short_sample_label(label: str, limit: int = 24) -> str:
    cleaned = " ".join((label or "").split()).strip("：:，,。 ")
    if not cleaned:
        cleaned = "中文叙事技巧"
    return cleaned if len(cleaned) <= limit else cleaned[:limit].rstrip() + "…"


# ---------------------------------------------------------------------------
# Chapter context assembly
# ---------------------------------------------------------------------------


def build_axis_context(project_dir: Path) -> str:
    """项目轴：宪法 + 故事规格摘要 + 文风档案 + 总纲 + 卷纲 + 本地一致性预警。"""
    parts: list[str] = []
    constitution = _read_capped(project_dir / CONSTITUTION_REL, AXIS_LIMITS["constitution"])
    if constitution:
        parts.append(f"## 创作宪法（红线）\n\n{constitution}")
    spec_block = spec_summary_block(parse_story_spec(project_dir))
    if spec_block:
        parts.append(f"## 故事规格摘要\n\n{spec_block}")
    style = _read_capped(project_dir / STYLE_REL, AXIS_LIMITS["style"])
    profile_block = render_style_profile_block(project_dir, resolve_style_profile_name(project_dir))
    style_parts = [part for part in (style, profile_block) if part]
    if style_parts:
        style_block = "\n\n".join(style_parts)
        parts.append(f"## 文风档案\n\n{style_block}")
    outline = _read_capped(project_dir / GLOBAL_OUTLINE_REL, AXIS_LIMITS["outline"])
    if outline:
        parts.append(f"## 全书总纲\n\n{outline}")
    volume = build_volume_axis_context(project_dir)
    if volume:
        parts.append(f"## 卷/幕结构\n\n{volume}")
    consistency = build_consistency_axis_context(project_dir)
    if consistency:
        parts.append(consistency)
    return "\n\n".join(parts)


def build_consistency_axis_context(project_dir: Path) -> str:
    try:
        from project_center import render_story_consistency_review

        return _cap_context_text(render_story_consistency_review(project_dir), AXIS_LIMITS["consistency"])
    except Exception:
        return ""


def build_volume_axis_context(project_dir: Path) -> str:
    try:
        from long_structure import volume_axis_block

        return volume_axis_block(project_dir, AXIS_LIMITS["volume"])
    except Exception:
        return ""


def build_rolling_memory(project_dir: Path) -> str:
    """滚动记忆四件套（capped）。"""
    sections = [
        ("全局事态摘要", GLOBAL_SUMMARY_REL, ROLLING_LIMITS["global_summary"]),
        ("最近章节摘要", RECENT_SUMMARY_REL, ROLLING_LIMITS["recent_summary"]),
        ("伏笔追踪表", FORESHADOW_REL, ROLLING_LIMITS["foreshadow"]),
        ("人物状态表", CHARACTER_STATE_REL, ROLLING_LIMITS["character_state"]),
    ]
    parts = []
    for label, rel, limit in sections:
        text = _read_capped(project_dir / rel, limit)
        if text:
            parts.append(f"## {label}\n\n{text}")
    return "\n\n".join(parts)


def build_chapter_context(project_dir: Path, rag: Any | None, chapter_outline: str) -> str:
    """完整章节上下文：项目轴 → 滚动记忆 → RAG 召回。"""
    parts: list[str] = []
    axis = build_axis_context(project_dir)
    if axis:
        parts.append(axis)
    rolling = build_rolling_memory(project_dir)
    if rolling:
        parts.append(rolling)
    active_volume = build_active_volume_context(project_dir, chapter_outline)
    if active_volume:
        parts.append(active_volume)
    if rag is not None:
        try:
            rag_ctx = rag.build_context(chapter_outline)
        except Exception:
            rag_ctx = ""
        if rag_ctx and rag_ctx.strip():
            parts.append(rag_ctx.strip())
    return "\n\n---\n\n".join(parts)


def build_active_volume_context(project_dir: Path, chapter_outline: str) -> str:
    try:
        from long_structure import active_volume_block, infer_chapter_num

        chapter_num = infer_chapter_num(chapter_outline)
        return active_volume_block(project_dir, chapter_num) if chapter_num else ""
    except Exception:
        return ""


def build_planning_context(project_dir: Path, target: str = "planning") -> str:
    """给世界观/总纲/角色/章纲等前期 AI 辅助统一注入项目轴。

    这让故事规格、创作宪法、文风档案和总纲不只服务正文生成，也会主动约束
    世界观、角色和大纲草案，避免前期草案各写各的。
    """
    parts: list[str] = []
    contract = planning_linkage_contract(target)
    if contract:
        parts.append(f"## 联动硬约束（不可忽略）\n\n{contract}")
    axis = build_axis_context(project_dir)
    if axis:
        parts.append(f"## 项目轴（所有策划草案必须遵守）\n\n{axis}")
    if target != "world":
        world = _read_capped(project_dir / WORLD_REL, PLANNING_LIMITS["world"])
        if world:
            parts.append(f"## 已有世界观（下游草案不得冲突）\n\n{world}")
    if target in {"character", "character_batch", "chapter"}:
        characters = _character_index_block(project_dir)
        if characters:
            parts.append(f"## 已有角色档案索引（避免重复或割裂）\n\n{characters}")
    if target == "chapter":
        rolling = build_rolling_memory(project_dir)
        if rolling:
            parts.append(f"## 滚动记忆（章纲需承接）\n\n{rolling}")
    return "\n\n---\n\n".join(parts)


def planning_linkage_contract(target: str) -> str:
    labels = {
        "world": "世界观草案",
        "outline": "总纲草案",
        "character": "角色档案草案",
        "character_batch": "批量角色档案草案",
        "chapter": "章纲草案",
    }
    label = labels.get(target, "策划草案")
    base = [
        f"- 本次输出是“{label}”，必须主动服务《故事规格》中的一句话概括、目标读者、核心冲突、类型卖点和成功标准。",
        "- 不允许只复述世界观模板；每个新增设定都要说明它如何推动人物选择、剧情冲突或读者追看点。",
        "- 若故事规格与既有世界观/总纲冲突，优先指出冲突并给出可合并方案，不要静默另起一套设定。",
        "- 输出开头必须包含“项目规格对齐”小节，列出本草案继承了哪些故事规格要点。",
    ]
    target_rules = {
        "world": [
            "- 世界观必须围绕目标读者、类型卖点、主角年龄/身份/核心关系设计规则和限制。",
            "- 核心规则必须能解释主角为什么行动、为什么受限、为什么产生长期冲突。",
        ],
        "outline": [
            "- 总纲必须承接世界观，但主线结构优先服务故事规格中的核心冲突和成功标准。",
            "- 每个阶段都要写明对应的技术/情感/伦理/关系推进点。",
        ],
        "character": [
            "- 角色档案必须承接故事规格中的主要角色定位、关系张力和目标读者期待。",
            "- 角色欲望、恐惧、秘密必须能持续制造剧情或情感冲突。",
        ],
        "character_batch": [
            "- 批量角色必须围绕故事规格中的主角、对手、情感牵引者、信息持有者等功能互相牵制。",
            "- 不要生成与主线无关的孤立角色。",
        ],
        "chapter": [
            "- 章纲必须承接故事规格、总纲、滚动记忆和伏笔表；每章至少推进一个规格中的卖点或成功标准。",
            "- 禁止写成与主线目标无关的单章事件。",
        ],
    }
    return "\n".join([*base, *target_rules.get(target, [])])


def append_planning_context(prompt: str, context: str) -> str:
    if not context.strip():
        return prompt
    return f"{context.strip()}\n\n---\n\n## 当前辅助任务输入\n\n{prompt.strip()}"


def build_linkage_report(project_dir: Path) -> dict[str, Any]:
    spec = parse_story_spec(project_dir)
    axis_present = {
        "创作宪法": bool(_read_capped(project_dir / CONSTITUTION_REL, 80)),
        "故事规格": any(spec.values()),
        "文风档案": bool(_read_capped(project_dir / STYLE_REL, 80) or resolve_style_profile_name(project_dir)),
        "全书总纲": bool(_read_capped(project_dir / GLOBAL_OUTLINE_REL, 80)),
        "卷/幕结构": bool(build_volume_axis_context(project_dir)),
    }
    consumers = [
        ("世界观 AI 辅助", "build_planning_context(target='world')", ["创作宪法", "故事规格", "文风档案", "全书总纲"]),
        ("总纲 AI 辅助", "build_planning_context(target='outline')", ["创作宪法", "故事规格", "文风档案", "全书总纲", "世界观"]),
        ("角色 AI 辅助", "build_planning_context(target='character')", ["创作宪法", "故事规格", "文风档案", "全书总纲", "世界观", "角色索引"]),
        ("章纲 AI 辅助", "build_planning_context(target='chapter')", ["创作宪法", "故事规格", "文风档案", "全书总纲", "卷/幕结构", "世界观", "角色索引", "滚动记忆"]),
        ("任务卡/伏笔识别/场景计划", "build_axis_context()", ["创作宪法", "故事规格", "文风档案", "全书总纲", "卷/幕结构"]),
        ("正文生成/修订/审计", "build_chapter_context()", ["创作宪法", "故事规格", "文风档案", "全书总纲", "卷/幕结构", "滚动记忆", "RAG"]),
        ("场景审稿", "build_axis_context()", ["创作宪法", "故事规格", "文风档案", "全书总纲", "卷/幕结构"]),
        ("AI味检查/文风检查", "build_axis_context()", ["创作宪法", "故事规格", "文风档案", "全书总纲", "卷/幕结构"]),
        ("章节质量诊断", "quality_diagnostics.write_quality_diagnostics()", ["章节任务卡", "正文稿件"]),
        ("人物状态维护", "build_axis_context()", ["创作宪法", "故事规格", "文风档案", "全书总纲", "卷/幕结构"]),
    ]
    rows = []
    for name, entry, uses in consumers:
        missing = [item for item in uses if item in axis_present and not axis_present[item]]
        rows.append({
            "模块": name,
            "联动入口": entry,
            "使用信息": "、".join(uses),
            "状态": "已联动" if not missing else "待补上游：" + "、".join(missing),
        })
    return {
        "axis_present": axis_present,
        "story_spec": spec_summary_block(spec),
        "consumers": rows,
    }


# ---------------------------------------------------------------------------
# Task card injection
# ---------------------------------------------------------------------------


def render_task_card_block(project_dir: Path, chapter_num: int) -> str:
    """把任务卡 JSON 渲染成 user message 末尾的强约束块。"""
    try:
        from structured_store import read_task_card
    except Exception:
        return ""
    card = read_task_card(project_dir, chapter_num)
    if card is None:
        return ""
    lines = [
        "## 本章结构化任务卡（必须严守）",
        "",
        f"- 章节模式：{card.chapter_mode}",
        f"- 结尾方式：{card.ending_style}",
        f"- 节奏：{card.pacing}",
        f"- 风格档案：{card.style_profile or '未指定'}",
        f"- 视角人物：{card.pov_character or '未指定'}",
        f"- 字数目标：{card.target_words or '未指定'}",
        f"- 时间线：{card.timeline or '未指定'}",
        f"- 章末悬念：{card.ending_hook or '（参考章纲）'}",
    ]
    if card.core_event:
        lines.extend(["", "### 本章核心事件", card.core_event.strip()])
    if card.emotional_curve:
        lines.extend(["", "### 情感弧线", card.emotional_curve.strip()])
    if card.foreshadowing_planted:
        lines.extend(["", "### 必须埋下的伏笔"])
        lines.extend(f"- {item}" for item in card.foreshadowing_planted)
    if card.foreshadowing_resolved:
        lines.extend(["", "### 必须收回的伏笔"])
        lines.extend(f"- {item}" for item in card.foreshadowing_resolved)
    if card.forbidden:
        lines.extend(["", "### 禁止事项（绝对不可出现）"])
        lines.extend(f"- {item}" for item in card.forbidden)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _split_sections(text: str) -> dict[str, str]:
    """按 `## N. 标题` 切分故事规格 markdown。"""
    sections: dict[str, str] = {}
    matches = list(SPEC_SECTION_PATTERN.finditer(text))
    for idx, match in enumerate(matches):
        title = match.group(1).strip()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        sections[title] = text[start:end].strip()
    return sections


def _extract_answer(section_text: str) -> str:
    if not section_text:
        return ""
    match = ANSWER_PATTERN.search(section_text)
    candidate = match.group(1) if match else section_text
    # 任一占位 token 还存在 → 视为未填（半填半空也不注入，避免给模型矛盾信息）
    if any(token in candidate for token in PLACEHOLDER_TOKENS):
        return ""
    cleaned = candidate.strip()
    return cleaned


def _read_capped(path: Path, limit: int) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n\n…（项目轴已截断，完整内容见原文件）"


def _cap_context_text(text: str, limit: int) -> str:
    text = text.strip()
    if not text:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n\n…（项目轴已截断，完整内容见原文件）"


def _character_index_block(project_dir: Path) -> str:
    char_dir = project_dir / CHARACTER_DIR_REL
    if not char_dir.exists():
        return ""
    lines = []
    for path in sorted(char_dir.glob("*.md")):
        if path.name == "角色模板.md" or "AI草案" in path.parts:
            continue
        text = _read_capped(path, 500)
        if text:
            lines.append(f"### {path.stem}\n\n{text}")
    block = "\n\n".join(lines)
    if len(block) > PLANNING_LIMITS["characters"]:
        return block[: PLANNING_LIMITS["characters"]].rstrip() + "\n\n…（角色索引已截断）"
    return block


def _render_template(template: str, values: dict[str, str]) -> str:
    rendered = template
    for key, val in values.items():
        text = "" if val is None else str(val)
        rendered = rendered.replace("{{ " + key + " }}", text)
        rendered = rendered.replace("{{" + key + "}}", text)
    return rendered


def _oneline(text: str, limit: int) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[:limit].rstrip() + "…"
