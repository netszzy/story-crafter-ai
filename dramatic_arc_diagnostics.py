"""
V2.7 戏剧结构诊断器。

它与本地 `quality_diagnostics.py` 共存：后者看句长、对白、套话等语言层指标；
本模块用 critic provider 或 mock fallback 看场景压力、人物弧光和画面可视性。
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from llm_router import LLMRouter
from project_archive import archive_existing
from novel_schemas import (
    ChapterDramaSnapshot,
    CharacterArcSignal,
    CinematicSample,
    DramaTrends,
    DramaticDiagnostics,
    SceneTension,
    model_to_json,
)
from prompt_assembly import build_axis_context


PROMPT_REL = "prompts/戏剧诊断.md"
CONFLICT_TERMS = ["必须", "不能", "代价", "风险", "威胁", "拒绝", "选择", "暴露", "秘密", "真相", "失去", "冻结"]
ACTION_TERMS = ["推", "按", "拿", "放", "走", "停", "看", "抬", "转", "握", "递", "坐", "站", "咬", "摸", "拉", "关", "开"]
SOUND_TERMS = ["说", "问", "喊", "响", "声", "喇叭", "雨", "脚步", "电话", "蜂鸣", "沉默"]
ABSTRACT_TERMS = ["复杂", "莫名", "情绪", "心情", "感觉", "说不出", "难以形容", "仿佛", "不禁", "忍不住"]
KNOWN_NAME_PATTERN = re.compile(r"(郁时谌|沈逐光|温漪|程栩白|阮眠|纪若棠|韩既白|莫春山|贺长明|林望)")


def diagnose_chapter_drama(
    project_dir: Path,
    chapter_num: int,
    chapter_text: str,
    task_card_json: str = "",
    character_briefs: str = "",
    llm: LLMRouter | None = None,
) -> DramaticDiagnostics:
    """主入口：返回章节戏剧诊断模型。"""
    project_dir = Path(project_dir)
    llm = llm or LLMRouter(project_dir=project_dir)
    if _should_mock(llm):
        diag = _mock_diagnostics(chapter_num, chapter_text)
        diag.provider_used = "mock"
        diag.model_used = "mock-dramatic-critic"
        return diag

    system_prompt = _build_system_prompt(project_dir)
    user_msg = _build_user_msg(chapter_text, task_card_json, character_briefs)
    raw = llm.critic_text(
        system_prompt=system_prompt,
        user_prompt=user_msg,
        workflow="dramatic-diagnose",
        role="dramatic-critic",
        max_tokens=4000,
    )
    return _parse_response(raw, chapter_num, llm, project_dir=project_dir, fallback_text=chapter_text)


def write_diagnostics(project_dir: Path, diag: DramaticDiagnostics) -> tuple[Path, Path]:
    """写入 JSON + Markdown 摘要，返回两个路径。"""
    project_dir = Path(project_dir)
    ch = f"{diag.chapter_number:03d}"
    log_dir = project_dir / "04_审核日志"
    json_path = log_dir / f"第{ch}章_戏剧诊断.json"
    md_path = log_dir / f"第{ch}章_戏剧诊断.md"
    log_dir.mkdir(parents=True, exist_ok=True)
    archive_existing(json_path)
    archive_existing(md_path)
    json_path.write_text(model_to_json(diag) + "\n", encoding="utf-8")
    md_path.write_text(_render_markdown(diag), encoding="utf-8")
    return md_path, json_path


def read_diagnostics(project_dir: Path, chapter_num: int) -> DramaticDiagnostics | None:
    path = Path(project_dir) / "04_审核日志" / f"第{chapter_num:03d}章_戏剧诊断.json"
    if not path.exists():
        return None
    try:
        return DramaticDiagnostics.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValidationError):
        return None


def diagnostics_to_revision_brief(diag: DramaticDiagnostics | dict[str, Any] | None) -> str:
    """把戏剧诊断转成给 reviser 的高优先级改稿任务。"""
    if not diag:
        return ""
    if isinstance(diag, dict):
        diag = DramaticDiagnostics.model_validate(diag)
    if not diag.top_revision_targets:
        return ""
    lines = [
        "## 戏剧诊断改稿任务（优先级最高）",
        "",
        f"- 压力曲线：{diag.pressure_curve_score}/100",
        f"- 人物弧光：{diag.character_arc_score}/100",
        f"- 画面可视性：{diag.cinematic_score}/100",
        "",
        "### 必改项",
    ]
    lines.extend(f"{idx}. {target}" for idx, target in enumerate(diag.top_revision_targets[:5], start=1))
    lines += [
        "",
        "### 改稿约束",
        "- 优先让代价、选择和人物动作变得可见。",
        "- 保留原章核心事件，不新增与项目轴冲突的新事实。",
    ]
    return "\n".join(lines).strip()


def build_character_briefs(project_dir: Path, chapter_text: str, max_chars: int = 4000) -> str:
    """抽取本章正文中出现的人物档案摘要，供戏剧诊断对照弧光。"""
    char_dir = Path(project_dir) / "00_世界观" / "角色档案"
    if not char_dir.exists():
        return ""
    blocks: list[str] = []
    for path in sorted(char_dir.glob("*.md")):
        if path.name == "角色模板.md":
            continue
        if path.stem not in chapter_text:
            continue
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            continue
        blocks.append(f"## {path.stem}\n\n{_clip(text, 900)}")
        if sum(len(block) for block in blocks) >= max_chars:
            break
    return "\n\n".join(blocks)[:max_chars]


def _build_system_prompt(project_dir: Path) -> str:
    template_path = Path(project_dir) / PROMPT_REL
    if not template_path.exists():
        template_path = Path(__file__).resolve().parent / PROMPT_REL
    template = template_path.read_text(encoding="utf-8") if template_path.exists() else ""
    schema = json.dumps(DramaticDiagnostics.model_json_schema(), ensure_ascii=False, indent=2)
    return (
        template.replace("{{ axis_context }}", build_axis_context(project_dir) or "（项目轴为空，按正文和任务卡评估）")
        .replace("{{ json_schema }}", schema)
        .strip()
    )


def _build_user_msg(chapter_text: str, task_card_json: str = "", character_briefs: str = "") -> str:
    return "\n\n".join([
        "## 本章主要人物档案\n\n" + (character_briefs.strip() or "（未提供，按正文显性信息判断）"),
        "## 章节任务卡\n\n" + (task_card_json.strip() or "（未提供）"),
        "## 本章正文\n\n" + chapter_text.strip(),
    ])


def _parse_response(
    raw: str,
    chapter_num: int,
    llm: LLMRouter | None = None,
    project_dir: Path | None = None,
    fallback_text: str = "",
) -> DramaticDiagnostics:
    """解析 LLM JSON，失败则降级 mock 并记录原文。"""
    try:
        payload = _extract_json_object(raw)
        data = json.loads(payload)
        data.setdefault("chapter_number", chapter_num)
        if llm is not None:
            data.setdefault("provider_used", getattr(llm, "CRITIC_PROVIDER", ""))
            data.setdefault("model_used", _critic_model_name(llm))
        diag = DramaticDiagnostics.model_validate(data)
        return _normalize_scores(diag)
    except (ValueError, json.JSONDecodeError, ValidationError) as exc:
        if project_dir is not None:
            _log_parse_failure(project_dir, chapter_num, raw, exc)
        diag = _mock_diagnostics(chapter_num, fallback_text or raw)
        diag.provider_used = "mock"
        diag.model_used = "mock-dramatic-critic"
        return diag


def _mock_diagnostics(chapter_num: int, text: str) -> DramaticDiagnostics:
    """本地启发式 mock，便于离线验收。"""
    paragraphs = _paragraphs(text)
    scenes = _mock_scenes(paragraphs)
    samples = _mock_cinematic_samples(paragraphs)
    characters = _mock_characters(text)

    pressure = _score_pressure(scenes)
    arc = _score_arc(characters)
    cinematic = _score_cinematic(samples)
    overall = _weighted_overall(pressure, arc, cinematic)
    targets = _mock_revision_targets(scenes, characters, samples)
    return DramaticDiagnostics(
        chapter_number=chapter_num,
        title=_extract_title(text),
        model_used="mock-dramatic-critic",
        provider_used="mock",
        pressure_curve_score=pressure,
        character_arc_score=arc,
        cinematic_score=cinematic,
        overall_drama_score=overall,
        scenes=scenes,
        characters=characters,
        cinematic_samples=samples,
        top_revision_targets=targets,
        is_mock=True,
    )


def _should_mock(llm: LLMRouter) -> bool:
    if not hasattr(llm, "critic_text"):
        return True
    mode = str(getattr(llm, "mode", "auto")).lower()
    if mode == "mock":
        return True
    if mode == "real":
        return False
    provider = str(getattr(llm, "CRITIC_PROVIDER", "deepseek")).lower()
    if not hasattr(llm, "_should_mock"):
        return False
    if provider == "openrouter":
        return bool(llm._should_mock("openrouter", "OPENROUTER_API_KEY"))
    return bool(llm._should_mock("deepseek", "DEEPSEEK_API_KEY"))


def _extract_json_object(raw: str) -> str:
    text = (raw or "").strip()
    fence = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", text)
    if fence:
        return fence.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("No JSON object found in dramatic diagnostics response")
    return text[start : end + 1]


def _paragraphs(text: str) -> list[str]:
    items = re.split(r"\n\s*\n+", (text or "").strip())
    if len(items) <= 1:
        items = [line for line in (text or "").splitlines() if line.strip()]
    cleaned = [" ".join(item.strip().split()) for item in items if _zh_count(item) >= 8 and not item.strip().startswith("#")]
    return cleaned or ["（正文为空或过短，无法形成有效场景）"]


def _mock_scenes(paragraphs: list[str]) -> list[SceneTension]:
    selected = paragraphs[:5]
    scenes = []
    for idx, paragraph in enumerate(selected, start=1):
        conflict_hits = _count_terms(paragraph, CONFLICT_TERMS)
        action_hits = _count_terms(paragraph, ACTION_TERMS)
        pressure = _clamp(2 + conflict_hits * 2 + min(action_hits, 3), 0, 10)
        clarity = _clamp(3 + conflict_hits + (2 if "“" in paragraph or '"' in paragraph else 0), 0, 10)
        scenes.append(SceneTension(
            scene_index=idx,
            scene_summary=_clip(paragraph, 30),
            must_do="让选择和行动显形" if conflict_hits else "本场必须补出清晰选择",
            cost_if_fail="关系、资源或秘密会付出代价" if conflict_hits else "代价尚不清晰",
            pressure_level=pressure,
            pressure_clarity=clarity,
        ))
    return scenes


def _mock_cinematic_samples(paragraphs: list[str]) -> list[CinematicSample]:
    samples = []
    for idx, paragraph in enumerate(paragraphs[:5], start=1):
        action = min(_count_terms(paragraph, ACTION_TERMS), 10)
        sound = min(_count_terms(paragraph, SOUND_TERMS), 10)
        abstract = min(_count_terms(paragraph, ABSTRACT_TERMS), 10)
        visual = _clamp(3 + action + min(_zh_count(paragraph) // 50, 3), 0, 10)
        samples.append(CinematicSample(
            paragraph_index=idx,
            excerpt=_clip(paragraph, 120),
            visual_score=visual,
            auditory_score=_clamp(2 + sound, 0, 10),
            body_action_score=_clamp(2 + action, 0, 10),
            abstract_word_ratio=abstract,
            rewrite_hint="把抽象判断改成可见动作、物件变化或明确代价。" if abstract >= 2 else "保留具体动作，补强选择和代价。",
        ))
    return samples


def _mock_characters(text: str) -> list[CharacterArcSignal]:
    names = []
    for match in KNOWN_NAME_PATTERN.finditer(text or ""):
        if match.group(1) not in names:
            names.append(match.group(1))
    if not names:
        names = ["主角"]
    characters = []
    for name in names[:5]:
        idx = (text or "").find(name)
        evidence = _clip((text or "")[max(idx, 0) : max(idx, 0) + 80], 80) if idx >= 0 else ""
        engaged = any(term in text for term in CONFLICT_TERMS)
        characters.append(CharacterArcSignal(
            name=name,
            flaw_or_desire="根据正文推断：目标、秘密或关系压力",
            engaged=engaged,
            evidence_quote=evidence if engaged else "",
            arc_movement="前进" if engaged else "未涉及",
        ))
    return characters


def _score_pressure(scenes: list[SceneTension]) -> int:
    if not scenes:
        return 0
    return _clamp(round(sum((s.pressure_level + s.pressure_clarity) / 2 for s in scenes) / len(scenes) * 10), 0, 100)


def _score_arc(characters: list[CharacterArcSignal]) -> int:
    if not characters:
        return 0
    engaged = sum(1 for item in characters if item.engaged)
    score = round(engaged / len(characters) * 100)
    score -= sum(10 for item in characters if item.arc_movement in {"停滞", "倒退"})
    return _clamp(score, 0, 100)


def _score_cinematic(samples: list[CinematicSample]) -> int:
    if not samples:
        return 0
    visible = sum((s.visual_score + s.auditory_score + s.body_action_score) / 3 for s in samples) / len(samples)
    abstract = sum(s.abstract_word_ratio for s in samples) / len(samples)
    return _clamp(round(visible * 10 - abstract * 5), 0, 100)


def _weighted_overall(pressure: int, arc: int, cinematic: int) -> int:
    value = 0.4 * pressure + 0.35 * arc + 0.25 * cinematic
    return _clamp(int(value + 0.5), 0, 100)


def _normalize_scores(diag: DramaticDiagnostics) -> DramaticDiagnostics:
    diag.pressure_curve_score = _clamp(diag.pressure_curve_score, 0, 100)
    diag.character_arc_score = _clamp(diag.character_arc_score, 0, 100)
    diag.cinematic_score = _clamp(diag.cinematic_score, 0, 100)
    diag.overall_drama_score = _weighted_overall(
        diag.pressure_curve_score,
        diag.character_arc_score,
        diag.cinematic_score,
    )
    return diag


def _mock_revision_targets(
    scenes: list[SceneTension],
    characters: list[CharacterArcSignal],
    samples: list[CinematicSample],
) -> list[str]:
    targets = []
    weak_scene = next((scene for scene in scenes if scene.pressure_level <= 4 or scene.pressure_clarity <= 4), None)
    if weak_scene:
        targets.append(f"场景{weak_scene.scene_index}：压力或代价不可见，补出角色必须选择什么以及拒绝后的具体损失。")
    idle_character = next((item for item in characters if not item.engaged), None)
    if idle_character:
        targets.append(f"{idle_character.name}：人物弧光未触发，让其欲望、恐惧或秘密在本章造成一次行动。")
    abstract_sample = next((sample for sample in samples if sample.abstract_word_ratio >= 2), None)
    if abstract_sample:
        targets.append(f"段落{abstract_sample.paragraph_index}：抽象情绪词偏多，用动作、物件和声音替换直接说明。")
    if not targets:
        targets.append("全章：保留当前具体动作优势，进一步强化章末选择的不可逆代价。")
    return targets[:5]


def _render_markdown(diag: DramaticDiagnostics) -> str:
    lines = [
        f"# 第{diag.chapter_number:03d}章 戏剧诊断",
        "",
        f"- 总分：{diag.overall_drama_score}/100",
        f"- 压力曲线：{diag.pressure_curve_score}/100",
        f"- 人物弧光：{diag.character_arc_score}/100",
        f"- 画面可视性：{diag.cinematic_score}/100",
        f"- 模型：{diag.provider_used}/{diag.model_used}",
        f"- Mock：{'是' if diag.is_mock else '否'}",
        "",
        "## 改稿优先级",
    ]
    lines.extend(f"{idx}. {item}" for idx, item in enumerate(diag.top_revision_targets[:5], start=1))
    lines += [
        "",
        "## 场景压力",
        "| 场景 | 概括 | 压力 | 清晰度 | 必须做 | 失败代价 |",
        "|---|---|---:|---:|---|---|",
    ]
    for scene in diag.scenes:
        lines.append(
            f"| {scene.scene_index} | {_cell(scene.scene_summary)} | {scene.pressure_level} | {scene.pressure_clarity} | {_cell(scene.must_do)} | {_cell(scene.cost_if_fail)} |"
        )
    lines += [
        "",
        "## 人物弧光",
        "| 人物 | 触发 | 弧光 | 证据 |",
        "|---|---|---|---|",
    ]
    for item in diag.characters:
        lines.append(f"| {_cell(item.name)} | {'是' if item.engaged else '否'} | {item.arc_movement} | {_cell(item.evidence_quote)} |")
    lines += [
        "",
        "## 画面样本",
        "| 段落 | 画面 | 声音 | 动作 | 抽象 | 建议 |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for sample in diag.cinematic_samples:
        lines.append(
            f"| {sample.paragraph_index} | {sample.visual_score} | {sample.auditory_score} | {sample.body_action_score} | {sample.abstract_word_ratio} | {_cell(sample.rewrite_hint)} |"
        )
    return "\n".join(lines).strip() + "\n"


def _log_parse_failure(project_dir: Path, chapter_num: int, raw: str, exc: Exception) -> Path:
    log_dir = Path(project_dir) / "logs" / "dramatic_diagnose_failures"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"第{chapter_num:03d}章_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    path.write_text(f"{type(exc).__name__}: {exc}\n\n{raw}", encoding="utf-8")
    return path


def _critic_model_name(llm: LLMRouter) -> str:
    provider = str(getattr(llm, "CRITIC_PROVIDER", "deepseek")).lower()
    if provider == "openrouter":
        return str(getattr(llm, "OPENROUTER_CRITIC_MODEL", ""))
    return str(getattr(llm, "DEEPSEEK_MODEL", ""))


def _extract_title(text: str) -> str:
    match = re.search(r"(?m)^#\s*(.+)$", text or "")
    return match.group(1).strip() if match else ""


def _count_terms(text: str, terms: list[str]) -> int:
    return sum(text.count(term) for term in terms)


def _zh_count(text: str) -> int:
    return sum(1 for char in text if "\u4e00" <= char <= "\u9fff")


def _clip(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


def _cell(text: str) -> str:
    return (text or "").replace("|", "｜").replace("\n", " ")


def _clamp(value: int | float, low: int, high: int) -> int:
    return max(low, min(high, int(round(value))))


# ─────────────────────────────────────────────────────────────────────────────
# V3.1 跨章节趋势统计
# ─────────────────────────────────────────────────────────────────────────────

def compute_drama_trends(project_dir: Path) -> DramaTrends:
    """扫描所有戏剧诊断 JSON，计算跨章节趋势。"""
    diag_dir = Path(project_dir) / "04_审核日志"
    if not diag_dir.exists():
        return DramaTrends()

    snapshots: list[ChapterDramaSnapshot] = []
    for path in sorted(diag_dir.glob("第*章_戏剧诊断.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        snapshots.append(ChapterDramaSnapshot(
            chapter_number=data.get("chapter_number", 0),
            pressure_curve_score=data.get("pressure_curve_score", 0),
            character_arc_score=data.get("character_arc_score", 0),
            cinematic_score=data.get("cinematic_score", 0),
            overall_drama_score=data.get("overall_drama_score", 0),
            is_mock=data.get("is_mock", False),
            generated_at=data.get("generated_at", ""),
        ))

    if not snapshots:
        return DramaTrends()

    # 按章号排序
    snapshots.sort(key=lambda s: s.chapter_number)

    # 3 章滚动均值
    real_scores = [s.overall_drama_score for s in snapshots if not s.is_mock]
    rolling = _rolling_avg(real_scores, window=3)

    # 趋势方向
    direction = _trend_direction(rolling, real_scores)

    # 三维度均值（排除 mock）
    real_snapshots = [s for s in snapshots if not s.is_mock]
    avg_pressure = sum(s.pressure_curve_score for s in real_snapshots) / len(real_snapshots) if real_snapshots else 0.0
    avg_arc = sum(s.character_arc_score for s in real_snapshots) / len(real_snapshots) if real_snapshots else 0.0
    avg_cinematic = sum(s.cinematic_score for s in real_snapshots) / len(real_snapshots) if real_snapshots else 0.0

    return DramaTrends(
        chapters=snapshots,
        rolling_avg_overall=rolling,
        trend_direction=direction,
        avg_pressure=round(avg_pressure, 1),
        avg_arc=round(avg_arc, 1),
        avg_cinematic=round(avg_cinematic, 1),
    )


def write_trends(project_dir: Path, trends: DramaTrends) -> Path:
    """写入趋势 JSON 到 04_审核日志/。"""
    from novel_schemas import write_json_model
    return write_json_model(Path(project_dir) / "04_审核日志" / "drama_trends.json", trends)


def _rolling_avg(values: list[int], window: int = 3) -> list[float]:
    if len(values) < window:
        return [sum(values) / len(values)] if values else []
    result: list[float] = []
    for i in range(len(values) - window + 1):
        result.append(round(sum(values[i:i + window]) / window, 1))
    return result


def _trend_direction(rolling: list[float], raw_scores: list[int] | None = None) -> str:
    scores: list[float] = rolling if len(rolling) >= 2 else (raw_scores or [])
    if len(scores) < 2:
        return "insufficient_data"
    diff = scores[-1] - scores[0]
    if diff > 2:
        return "improving"
    elif diff < -2:
        return "declining"
    return "stable"
