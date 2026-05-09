"""
Structured schemas for the novel writing workspace.

V0.3 keeps Markdown as the human-editable source of truth, while writing JSON
mirrors for review reports, chapter memory, and foreshadowing. These schemas are
small on purpose: strict enough for consistency checks, flexible enough for the
current file-based workflow.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CharacterCard(BaseModel):
    id: str
    name: str
    role: str = ""
    source_path: str = ""
    summary: str = ""
    updated_at: str = Field(default_factory=now_iso)


class ChapterTaskCard(BaseModel):
    chapter_number: int
    title: str = ""
    status: Literal["draft", "confirmed"] = "draft"
    chapter_mode: Literal["plot", "bridge", "interior", "atmosphere", "epilogue"] = "plot"
    ending_style: Literal["hook", "cliffhanger", "open", "echo"] = "hook"
    pacing: Literal["fast", "normal", "slow_burn"] = "normal"
    style_profile: str = ""
    pov_character: str = ""
    target_words: str = ""
    timeline: str = ""
    core_event: str = ""
    emotional_curve: str = ""
    foreshadowing_planted: list[str] = Field(default_factory=list)
    foreshadowing_resolved: list[str] = Field(default_factory=list)
    ending_hook: str = ""
    technique_focus: list[str] = Field(default_factory=list)
    forbidden: list[str] = Field(default_factory=list)
    source_path: str = ""
    updated_at: str = Field(default_factory=now_iso)
    confirmed_at: str | None = None


class ScenePlan(BaseModel):
    chapter_number: int
    scene_number: int
    title: str = ""
    status: Literal["planned", "drafted", "reviewed", "rewritten", "selected"] = "planned"
    pov_character: str = ""
    location: str = ""
    scene_goal: str = ""
    conflict: str = ""
    emotional_tone: str = ""
    required_information: list[str] = Field(default_factory=list)
    forbidden_information: list[str] = Field(default_factory=list)
    estimated_words: int | None = None
    selected_draft_path: str = ""
    diagnostic_score: int | None = None
    diagnostic_notes: list[str] = Field(default_factory=list)
    updated_at: str = Field(default_factory=now_iso)


class SceneDiagnosticNote(BaseModel):
    """场景级轻量诊断（纯规则，零 API）。"""

    chapter_number: int
    scene_number: int
    conflict_visible: bool = False
    body_action_density: float = 0.0
    dialogue_advances: bool = True
    notes: list[str] = Field(default_factory=list)
    score: int = Field(ge=0, le=10, default=0)


class ForeshadowingItem(BaseModel):
    id: str
    planted_chapter: str = ""
    content: str = ""
    status: Literal["pending", "resolved", "abandoned", "unknown"] = "unknown"
    planned_resolution_chapter: str = ""
    updated_at: str = Field(default_factory=now_iso)


class CharacterState(BaseModel):
    name: str
    location: str = ""
    physical_state: str = ""
    emotional_state: str = ""
    known_information: list[str] = Field(default_factory=list)
    possessions: list[str] = Field(default_factory=list)
    goal: str = ""
    relationship_changes: list[str] = Field(default_factory=list)
    chapter_number: int = 0
    source_path: str = ""
    updated_at: str = Field(default_factory=now_iso)


class ReviewIssue(BaseModel):
    location: str = ""
    basis: str = ""
    suggestion: str = ""
    severity: Literal["high", "medium", "low", "unknown"] = "unknown"


class ReviewReport(BaseModel):
    target_type: Literal["chapter", "scene"] = "chapter"
    target_id: str
    chapter_number: int
    reviewer_role: str = "critic"
    model_name: str = ""
    source_markdown_path: str = ""
    issues: list[ReviewIssue] = Field(default_factory=list)
    raw_text: str = ""
    created_at: str = Field(default_factory=now_iso)


class ChapterMemory(BaseModel):
    chapter_number: int
    title: str = ""
    source_markdown_path: str = ""
    summary: str = ""
    events: list[str] = Field(default_factory=list)
    character_state_changes: dict[str, str] = Field(default_factory=dict)
    new_facts: list[str] = Field(default_factory=list)
    foreshadowing_added: list[str] = Field(default_factory=list)
    foreshadowing_resolved: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    timeline_update: list[str] = Field(default_factory=list)
    style_notes: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=now_iso)


class ProjectWorkflowStep(BaseModel):
    key: str
    name: str
    status: Literal["missing", "draft", "ready", "active", "complete"] = "missing"
    detail: str = ""
    source_path: str = ""


class ProjectStatusReport(BaseModel):
    version: str = "1.0"
    workflow: list[ProjectWorkflowStep] = Field(default_factory=list)
    metrics: dict[str, int] = Field(default_factory=dict)
    blockers: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    next_actions: list[str] = Field(default_factory=list)
    drama_trends: DramaTrends | None = None
    generated_at: str = Field(default_factory=now_iso)


class SceneTension(BaseModel):
    """单场戏的戏剧压力分析。"""

    scene_index: int
    scene_summary: str = ""
    must_do: str = ""
    cost_if_fail: str = ""
    pressure_level: int = Field(ge=0, le=10)
    pressure_clarity: int = Field(ge=0, le=10)


class CharacterArcSignal(BaseModel):
    """本章主要人物的弧光信号。"""

    name: str
    flaw_or_desire: str = ""
    engaged: bool = False
    evidence_quote: str = ""
    arc_movement: Literal["前进", "停滞", "倒退", "未涉及"] = "未涉及"


class CinematicSample(BaseModel):
    """抽样段落的画面感评估。"""

    paragraph_index: int
    excerpt: str
    visual_score: int = Field(ge=0, le=10)
    auditory_score: int = Field(ge=0, le=10)
    body_action_score: int = Field(ge=0, le=10)
    abstract_word_ratio: int = Field(ge=0, le=10)
    rewrite_hint: str = ""


class DramaticDiagnostics(BaseModel):
    """章节戏剧结构诊断报告。"""

    chapter_number: int
    title: str = ""
    model_used: str = ""
    provider_used: str = ""
    generated_at: str = Field(default_factory=now_iso)
    pressure_curve_score: int = Field(ge=0, le=100)
    character_arc_score: int = Field(ge=0, le=100)
    cinematic_score: int = Field(ge=0, le=100)
    overall_drama_score: int = Field(ge=0, le=100)
    scenes: list[SceneTension] = Field(default_factory=list)
    characters: list[CharacterArcSignal] = Field(default_factory=list)
    cinematic_samples: list[CinematicSample] = Field(default_factory=list)
    top_revision_targets: list[str] = Field(default_factory=list)
    is_mock: bool = False


# ── V5.0-beta2 文学批评层与风格法庭 ───────────────────────────────────────


class MemorableMoment(BaseModel):
    """文学批评层识别的可记忆瞬间。"""

    quote: str = ""
    why_memorable: str = ""
    fragility: str = ""


class LiteraryView(BaseModel):
    """主观文学批评视角，不参与分数裁决。"""

    chapter_number: int
    title: str = ""
    model_used: str = ""
    provider_used: str = ""
    generated_at: str = Field(default_factory=now_iso)
    memorable_moments: list[MemorableMoment] = Field(default_factory=list)
    unsaid_tension: list[str] = Field(default_factory=list)
    moral_ambiguity: list[str] = Field(default_factory=list)
    self_deception_signals: list[str] = Field(default_factory=list)
    reader_residue: list[str] = Field(default_factory=list)
    literary_risks: list[str] = Field(default_factory=list)
    cannot_be_quantified: bool = False
    is_mock: bool = False


class StyleCourtIssue(BaseModel):
    """风格法庭裁决中的单条议题。"""

    source: str = ""
    issue: str = ""
    reason: str = ""
    finding_key: str = ""


class StyleCourtDecision(BaseModel):
    """工程诊断与文学保护冲突时的裁决结果。"""

    chapter_number: int
    chapter_mode: str = ""
    style_profile: str = ""
    generated_at: str = Field(default_factory=now_iso)
    confirmed_issues: list[StyleCourtIssue] = Field(default_factory=list)
    contested_issues: list[StyleCourtIssue] = Field(default_factory=list)
    literary_priorities: list[str] = Field(default_factory=list)
    cannot_be_quantified: bool = False
    is_mock: bool = False


class ProseSampleEntry(BaseModel):
    """样本池中的单条文风样本。"""

    text: str
    source_chapter: int
    technique_label: str = ""
    cinematic_score: int = 0
    locked: bool = False
    excluded: bool = False
    added_at: str = Field(default_factory=now_iso)


class ChapterDramaSnapshot(BaseModel):
    """单章戏剧诊断快照，用于跨章趋势计算。"""

    chapter_number: int
    pressure_curve_score: int = 0
    character_arc_score: int = 0
    cinematic_score: int = 0
    overall_drama_score: int = 0
    is_mock: bool = False
    generated_at: str = ""


class DramaTrends(BaseModel):
    """跨章节戏剧诊断趋势。"""

    chapters: list[ChapterDramaSnapshot] = Field(default_factory=list)
    rolling_avg_overall: list[float] = Field(default_factory=list)
    trend_direction: Literal["improving", "declining", "stable", "insufficient_data"] = "insufficient_data"
    avg_pressure: float = 0.0
    avg_arc: float = 0.0
    avg_cinematic: float = 0.0
    generated_at: str = Field(default_factory=now_iso)


# ── V4.0 编辑备忘录 ────────────────────────────────────────────────────────


class MemoItem(BaseModel):
    """编辑备忘录中的单条行动项。"""

    priority: Literal["P0", "P1", "P2"] = "P1"
    source: str = ""
    location: str = ""
    issue: str = ""
    action: str = ""
    acceptance: str = ""


class DiagnosticReservation(BaseModel):
    """作家对诊断建议的裁决记录（V5.0-rc1 三态裁决）。"""

    action: Literal["adopt", "protect", "rebut"] = "protect"
    diagnostic_source: str = "quality"
    rejected_advice: str = ""
    writer_reason: str = ""
    finding_key: str = ""
    created_at: str = Field(default_factory=now_iso)


class EditorMemo(BaseModel):
    """编辑备忘录 — 多项诊断的统一合成输出。"""

    chapter_number: int
    title: str = ""
    style_profile: str = ""
    chapter_mode: str = ""
    reservations: list[DiagnosticReservation] = Field(default_factory=list)
    model_used: str = ""
    provider_used: str = ""
    generated_at: str = Field(default_factory=now_iso)
    top_3_must_fix: list[MemoItem] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    score_summary: dict[str, int] = Field(default_factory=dict)
    ready_to_finalize: bool = False
    overall_assessment: str = ""
    is_mock: bool = False


# ── V4.0 Phase B 角色声音指纹 ────────────────────────────────────────────────


class CharacterVoiceProfile(BaseModel):
    """单角色对白声音特征。"""

    character_name: str
    dialogue_count: int = 0
    avg_sentence_length: float = 0.0
    top_10_words: list[str] = Field(default_factory=list)
    particle_frequency: dict[str, float] = Field(default_factory=dict)
    rhetorical_question_ratio: float = 0.0
    sample_lines: list[str] = Field(default_factory=list)


class VoiceFingerprint(BaseModel):
    """章节角色声音指纹诊断。"""

    chapter_number: int
    profiles: list[CharacterVoiceProfile] = Field(default_factory=list)
    flagged_pairs: list[dict] = Field(default_factory=list)
    generated_at: str = Field(default_factory=now_iso)
    is_mock: bool = False


# ── V5.0-rc1 项目级文学健康（三指标替代单分数） ──────────────────────────────


class ChapterHealthSnapshot(BaseModel):
    """单章三维健康快照。"""

    chapter_number: int
    engineering_sturdiness: float = 0.0
    literary_density: float = 0.0
    style_consistency: float = 0.0
    has_draft: bool = False
    memorable_moments_count: int = 0
    score_quality: int | None = None


class ProjectHealthSnapshot(BaseModel):
    """V5.0-rc1 项目级文学健康，三指标独立显示，不合成总分。"""

    generated_at: str = Field(default_factory=now_iso)
    total_chapters_diagnosed: int = 0
    total_chapters: int = 0

    engineering_sturdiness: float = 0.0
    literary_density: float = 0.0
    style_consistency: float = 0.0

    engineering_trend: str = "stable"
    literary_trend: str = "stable"
    style_trend: str = "stable"

    chapter_snapshots: list[ChapterHealthSnapshot] = Field(default_factory=list)

    weakest_chapter_engineering: int | None = None
    weakest_chapter_literary: int | None = None
    most_style_drifted_chapter: int | None = None


def model_to_json(model: BaseModel) -> str:
    return model.model_dump_json(indent=2)


def write_json_model(path: str | Path, model: BaseModel) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(model_to_json(model) + "\n", encoding="utf-8")
    return target
