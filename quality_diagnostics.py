"""
V1.8 chapter quality diagnostics.

This module is deliberately deterministic and local. It complements LLM-based
logic audit by checking pacing, sentence rhythm, dialogue ratio, cliche density,
task-card alignment, and ending-hook strength without spending model tokens.
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from style_profiles import get_style_profile, merge_cliche_terms, resolve_style_profile_name

VERSION = "5.0-alpha2"

OPENING_HOOK_TERMS = [
    "为什么",
    "谁",
    "不对",
    "异常",
    "秘密",
    "失踪",
    "血",
    "死",
    "信",
    "照片",
    "门外",
    "电话",
    "必须",
    "不能",
    "决定",
    "？",
    "?",
]

CLICHE_TERMS = {
    "不禁": {"hint": "改成具体动作或停顿", "tolerable_in": []},
    "忍不住": {"hint": "改成动作的失控瞬间", "tolerable_in": []},
    "一丝": {"hint": "改成可见的细小反应", "tolerable_in": []},
    "一抹": {"hint": "改成具体颜色、光线或表情变化", "tolerable_in": []},
    "一股": {"hint": "改成具体来源、温度或身体反应", "tolerable_in": []},
    "涌上心头": {"hint": "落到喉咙、手、呼吸或停顿", "tolerable_in": []},
    "空气仿佛凝固": {"hint": "用声音消失、动作停顿或物件细节替换", "tolerable_in": []},
    "眼神复杂": {"hint": "写清看向哪里、避开什么、停多久", "tolerable_in": []},
    "心中一震": {"hint": "落到身体反应或动作失误", "tolerable_in": []},
    "下意识": {"hint": "直接写动作，不解释意识层级", "tolerable_in": ["high_tension"]},
    "说不出话来": {"hint": "用沉默里的动作、环境声或第三人反应替换", "tolerable_in": ["interior"]},
    "陷入沉默": {"hint": "用环境声、第三人观察或物件代替", "tolerable_in": ["interior"]},
    "深吸一口气": {"hint": "落到喉咙、胸口或停顿一拍", "tolerable_in": ["high_tension"]},
}

OPEN_ENDING_TERMS = [
    "灯熄了",
    "灯灭了",
    "窗外",
    "远处",
    "一直",
    "没有回头",
    "无人回答",
    "风还在",
    "雨还在",
    "水声",
    "脚步声",
    "空着",
    "留在原地",
    "慢慢暗下去",
    "最后一盏灯",
]

SLOW_CHAPTER_MODES = {"interior", "atmosphere", "bridge"}
INTERIOR_STYLE_PROFILES = {
    "wang_xiaobo",
    "王小波",
    "zhang_ailing",
    "张爱玲",
    "murakami_translation",
    "村上译介派",
}
PROTECTED_CONFLICT_ITEMS = {"冲突信号偏弱", "角色主动性偏弱", "追读张力偏弱"}
PROTECTED_INTERIOR_ITEMS = PROTECTED_CONFLICT_ITEMS | {"情绪身体化偏弱", "对白比例偏低"}

CHAPTER_MODE_THRESHOLDS = {
    "plot": {"conflict_min": 1.5, "dialogue_min": 0.08, "dialogue_max": 0.45, "ending_required": True},
    "bridge": {"conflict_min": 0.5, "dialogue_min": 0.05, "dialogue_max": 0.30, "ending_required": False},
    "interior": {"conflict_min": 0.0, "dialogue_min": 0.0, "dialogue_max": 0.15, "ending_required": True},
    "atmosphere": {"conflict_min": 0.0, "dialogue_min": 0.0, "dialogue_max": 0.10, "ending_required": True},
    "epilogue": {"conflict_min": 0.5, "dialogue_min": 0.10, "dialogue_max": 0.40, "ending_required": True},
}

FINDING_SCORE_PENALTIES = {
    "对白比例偏低": 8,
    "对白比例偏高": 8,
    "平均句长偏长": 10,
    "平均句长偏短": 6,
    "句式节奏过平": 8,
    "长段落过多": 8,
    "AI/网文化套话命中": 9,
    "章首抓力偏弱": 8,
    "章末钩子偏弱": 10,
    "章末余味偏弱": 8,
    "冲突信号偏弱": 10,
    "角色主动性偏弱": 8,
    "可感细节偏少": 6,
    "情绪身体化偏弱": 5,
    "追读张力偏弱": 8,
    "文气质地偏薄": 6,
    "说明性句子偏多": 8,
    "任务卡对齐不足": 6,
}

HOOK_TERMS = [
    "忽然",
    "突然",
    "门外",
    "电话",
    "短信",
    "邮件",
    "信封",
    "照片",
    "血",
    "死",
    "失踪",
    "未来",
    "真相",
    "秘密",
    "不是",
    "为什么",
    "谁",
    "？",
    "?",
    "！",
    "!",
]

CONFLICT_TERMS = [
    "冲突",
    "代价",
    "风险",
    "威胁",
    "追问",
    "隐瞒",
    "拒绝",
    "选择",
    "必须",
    "不能",
    "失去",
    "暴露",
    "怀疑",
    "阻止",
    "逼近",
    "交换",
    "真相",
    "秘密",
]

AGENCY_TERMS = [
    "决定",
    "选择",
    "拒绝",
    "追问",
    "推开",
    "拿起",
    "藏",
    "撒谎",
    "承认",
    "离开",
    "留下",
    "交易",
    "试探",
    "逼问",
    "反击",
    "转身",
]

SENSORY_TERMS = [
    "手",
    "指",
    "门",
    "窗",
    "雨",
    "灯",
    "血",
    "钥匙",
    "照片",
    "信封",
    "手机",
    "屏幕",
    "气味",
    "声音",
    "脚步",
    "桌",
    "杯",
]

BODY_EMOTION_TERMS = [
    "喉咙",
    "胸口",
    "指尖",
    "掌心",
    "脊背",
    "肩",
    "呼吸",
    "心跳",
    "冷汗",
    "僵",
    "颤",
    "疼",
    "发紧",
    "发麻",
]

INTRIGUE_TERMS = [
    "线索",
    "异常",
    "证据",
    "名单",
    "录音",
    "旧案",
    "日期",
    "编号",
    "档案",
    "钥匙",
    "照片",
    "信",
    "监控",
    "失踪",
    "谎",
    "秘密",
    "真相",
]

EXPOSITION_TERMS = [
    "因为",
    "原来",
    "事实上",
    "也就是说",
    "这意味着",
    "所谓",
    "据说",
    "传说",
    "规则是",
    "他知道",
    "她知道",
    "他们知道",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def zh_count(text: str) -> int:
    return sum(1 for char in text if "\u4e00" <= char <= "\u9fff")


def split_sentences(text: str) -> list[str]:
    rough = re.split(r"(?<=[。！？!?；;])|\n+", text)
    return [item.strip() for item in rough if zh_count(item) > 0]


def paragraph_lengths(text: str) -> list[int]:
    return [zh_count(p) for p in re.split(r"\n\s*\n+", text) if zh_count(p) > 0]


def dialogue_segments(text: str) -> list[str]:
    segments = re.findall(r"[“\"]([^”\"]{1,500})[”\"]", text)
    line_segments = [
        line.strip()
        for line in text.splitlines()
        if line.strip().startswith(("「", "『", "- ")) and zh_count(line) > 0
    ]
    return segments + line_segments


def safe_div(num: float, den: float) -> float:
    return num / den if den else 0.0


def term_hits(text: str, terms: list[str] | dict[str, Any]) -> int:
    return sum(text.count(term) for term in terms)


def _open_ending_hits(text: str) -> list[str]:
    return [term for term in OPEN_ENDING_TERMS if term in (text or "")]


def _chapter_context_tags(
    text: str,
    *,
    chapter_mode: str = "",
    pacing: str = "",
) -> set[str]:
    tags: set[str] = set()
    mode = (chapter_mode or "").strip().lower()
    if mode:
        tags.add(mode)
    if (pacing or "").strip().lower() == "slow_burn":
        tags.add("slow_burn")
    high_tension_terms = [
        "追",
        "逃",
        "枪",
        "刀",
        "血",
        "危险",
        "威胁",
        "逼近",
        "爆炸",
        "坠",
        "死",
        "不能",
        "必须",
    ]
    if any(term in (text or "") for term in high_tension_terms):
        tags.add("high_tension")
    if any(term in (text or "") for term in ["死亡", "死", "尸", "葬", "血", "医院", "告别", "遗像", "丧"]):
        tags.add("major_loss")
    return tags


def _cliche_hits(text: str, context_tags: set[str] | None = None, style_profile: str = "", project_dir: str | Path | None = None) -> dict[str, int]:
    tags = context_tags or set()
    hits: dict[str, int] = {}
    for term, meta in merge_cliche_terms(CLICHE_TERMS, style_profile, project_dir=project_dir).items():
        count = (text or "").count(term)
        if not count:
            continue
        if meta.get("allow") is True:
            continue
        tolerable = set(meta.get("tolerable_in", []))
        if "__all__" in tolerable or (tolerable and tolerable & tags):
            continue
        hits[term] = count
    return hits


def _has_cliche_hit(text: str, context_tags: set[str] | None = None) -> bool:
    return bool(_cliche_hits(text, context_tags))


def exposition_sentence_ratio(sentences: list[str]) -> float:
    if not sentences:
        return 0.0
    hits = sum(1 for sentence in sentences if any(term in sentence for term in EXPOSITION_TERMS))
    return safe_div(hits, len(sentences))


def stdev(values: list[int]) -> float:
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / len(values))


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def writer_overrides_path(project_dir: str | Path, chapter_num: int) -> Path:
    return Path(project_dir) / "04_审核日志" / f"第{chapter_num:03d}章_诊断豁免.json"


def read_writer_overrides(project_dir: str | Path, chapter_num: int) -> list[dict[str, Any]]:
    data = _load_json(writer_overrides_path(project_dir, chapter_num))
    raw = data.get("overrides", []) if isinstance(data, dict) else []
    return [item for item in raw if isinstance(item, dict)]


def write_writer_override(
    project_dir: str | Path,
    chapter_num: int,
    *,
    rejected_advice: str,
    writer_reason: str,
    diagnostic_source: str = "quality",
    finding_key: str = "",
    action: str = "protect",
) -> Path:
    """写入作家裁决记录（V5.0-rc1 三态裁决：adopt / protect / rebut）。"""
    if not rejected_advice.strip():
        return writer_overrides_path(project_dir, chapter_num)
    path = writer_overrides_path(project_dir, chapter_num)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = _load_json(path) or {"version": "5.0-rc1", "chapter_number": chapter_num, "overrides": []}
    data.setdefault("version", "5.0-rc1")
    rows = data.setdefault("overrides", [])
    record = {
        "action": action,
        "diagnostic_source": diagnostic_source,
        "rejected_advice": rejected_advice,
        "writer_reason": writer_reason,
        "finding_key": finding_key or f"{diagnostic_source}:{rejected_advice}",
        "created_at": now_iso(),
    }
    if not any(_override_matches_record(item, record) for item in rows if isinstance(item, dict)):
        rows.append(record)
    else:
        for item in rows:
            if isinstance(item, dict) and _override_matches_record(item, record):
                item.update(record)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def _override_matches_record(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return bool(
        left.get("finding_key") and left.get("finding_key") == right.get("finding_key")
        or left.get("rejected_advice") == right.get("rejected_advice")
    )


def _finding_key(finding: dict[str, Any], default_source: str = "quality") -> str:
    source = str(finding.get("diagnostic_source") or finding.get("source") or default_source).strip() or default_source
    item = str(finding.get("item") or finding.get("issue") or finding.get("rejected_advice") or "").strip()
    return f"{source}:{item}"


def apply_writer_overrides(report: dict[str, Any], overrides: list[dict[str, Any]] | dict[str, Any] | None) -> dict[str, Any]:
    """V5.0-rc1 三态裁决：adopt=采纳下次改 / protect=保护不修 / rebut=反驳诊断。

    adopt: 保持原 level，不退分，记录作家同意修
    protect: 标记 accepted_by_writer，退分，排除出 must_fix
    rebut: 标记 rebutted_by_writer，退分，排除出 must_fix
    """
    if isinstance(overrides, dict):
        override_rows = [item for item in overrides.get("overrides", []) if isinstance(item, dict)]
    else:
        override_rows = [item for item in (overrides or []) if isinstance(item, dict)]

    findings = report.get("findings", [])
    if not isinstance(findings, list):
        return report
    if not findings:
        return report
    matched: list[dict[str, Any]] = []
    score_refund = 0
    for finding in findings:
        if not isinstance(finding, dict):
            continue
        finding.setdefault("diagnostic_source", "quality")
        finding.setdefault("finding_key", _finding_key(finding))
        for override in override_rows:
            if _override_matches_finding(override, finding):
                action = str(override.get("action", "protect") or "protect").strip()
                if action == "adopt":
                    # 作家采纳：保持活跃，不退分，记录标记
                    if finding.get("level") not in ("adopted_by_writer",):
                        finding["original_level"] = finding.get("level", "")
                    finding["writer_action"] = "adopt"
                    finding["writer_reason"] = str(override.get("writer_reason", "") or "")
                    finding["override_created_at"] = str(override.get("created_at", "") or "")
                elif action == "rebut":
                    # 作家反驳：标记 rebutted_by_writer，退分，排除出 must_fix
                    if finding.get("level") not in ("rebutted_by_writer",):
                        finding["original_level"] = finding.get("level", "")
                        finding["level"] = "rebutted_by_writer"
                        score_refund += _finding_penalty(finding)
                    finding["writer_action"] = "rebut"
                    finding["writer_reason"] = str(override.get("writer_reason", "") or "")
                    finding["override_created_at"] = str(override.get("created_at", "") or "")
                else:
                    # protect（默认）：现有行为，标记 accepted_by_writer
                    if finding.get("level") not in ("accepted_by_writer",):
                        finding["original_level"] = finding.get("level", "")
                        finding["level"] = "accepted_by_writer"
                        score_refund += _finding_penalty(finding)
                    finding["writer_action"] = "protect"
                    finding["writer_reason"] = str(override.get("writer_reason", "") or "")
                    finding["override_created_at"] = str(override.get("created_at", "") or "")
                matched.append({
                    "action": action,
                    "diagnostic_source": finding.get("diagnostic_source", "quality"),
                    "rejected_advice": finding.get("item", ""),
                    "writer_reason": finding.get("writer_reason", ""),
                    "finding_key": finding.get("finding_key", ""),
                })
                break

    if matched:
        before = int(report.get("score", 0) or 0)
        report["score_before_writer_overrides"] = before
        report["score"] = max(0, min(100, before + score_refund))
        report["grade"] = _grade_for_score(int(report["score"]))
        report["writer_overrides"] = matched
    else:
        report.setdefault("writer_overrides", [])
    return report


def _override_matches_finding(override: dict[str, Any], finding: dict[str, Any]) -> bool:
    key = str(override.get("finding_key", "") or "").strip()
    if key and key == str(finding.get("finding_key", "") or ""):
        return True
    rejected = str(override.get("rejected_advice", "") or "").strip()
    item = str(finding.get("item", "") or "").strip()
    return bool(rejected and (rejected == item or rejected in item or item in rejected))


def _finding_penalty(finding: dict[str, Any]) -> int:
    if "score_penalty" in finding:
        try:
            return int(finding.get("score_penalty") or 0)
        except (TypeError, ValueError):
            pass
    return FINDING_SCORE_PENALTIES.get(str(finding.get("item", "")), 0)


def _grade_for_score(score: int) -> str:
    return "优秀" if score >= 85 else "可用" if score >= 70 else "需打磨" if score >= 55 else "高风险"


def _active_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """排除作家已保护/反驳的诊断，被采纳的保持活跃。"""
    return [
        item for item in findings
        if isinstance(item, dict) and item.get("level") not in ("accepted_by_writer", "rebutted_by_writer")
    ]


def _latest_chapter_text(project_dir: Path, chapter_num: int) -> tuple[str, str]:
    ch = f"{chapter_num:03d}"
    for rel in [
        f"02_正文/第{ch}章_定稿.md",
        f"02_正文/第{ch}章_修订稿.md",
        f"02_正文/第{ch}章_草稿.md",
    ]:
        path = project_dir / rel
        if path.exists():
            text = path.read_text(encoding="utf-8")
            if text.strip():
                return rel, text
    return "", ""


def _text_tokens(text: str) -> set[str]:
    return set(re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,12}", text))


def _field_covered(field_value: str, chapter_text: str) -> bool | None:
    value = (field_value or "").strip()
    if not value:
        return None
    tokens = _text_tokens(value)
    if not tokens:
        return None
    chapter_tokens = _text_tokens(chapter_text)
    hits = len(tokens & chapter_tokens)
    return hits >= max(1, min(3, len(tokens) // 3))


def _task_card_alignment(project_dir: Path, chapter_num: int, chapter_text: str) -> dict[str, Any]:
    ch = f"{chapter_num:03d}"
    card_path = project_dir / "01_大纲" / "章纲" / f"第{ch}章_task_card.json"
    card = _load_json(card_path)
    project_style_profile = resolve_style_profile_name(project_dir, chapter_num)
    if not card:
        return {
            "task_card_path": str(card_path.relative_to(project_dir)).replace("\\", "/"),
            "available": False,
            "chapter_mode": "plot",
            "ending_style": "hook",
            "pacing": "normal",
            "style_profile": project_style_profile,
            "checks": [],
            "forbidden_hits": [],
        }

    checks = []
    for key, label in [
        ("core_event", "核心事件"),
        ("emotional_curve", "情绪曲线"),
        ("ending_hook", "章末钩子"),
    ]:
        covered = _field_covered(str(card.get(key, "")), chapter_text)
        if covered is not None:
            checks.append({"field": key, "label": label, "covered": covered, "value": card.get(key, "")})

    forbidden = [str(item).strip() for item in card.get("forbidden", []) if str(item).strip()]
    forbidden_hits = [item for item in forbidden if item and item in chapter_text]
    planted = [str(item).strip() for item in card.get("foreshadowing_planted", []) if str(item).strip()]
    planted_hits = [item for item in planted if _field_covered(item, chapter_text)]

    return {
        "task_card_path": str(card_path.relative_to(project_dir)).replace("\\", "/"),
        "available": True,
        "status": card.get("status", ""),
        "chapter_mode": str(card.get("chapter_mode", "plot") or "plot"),
        "ending_style": str(card.get("ending_style", "hook") or "hook"),
        "pacing": str(card.get("pacing", "normal") or "normal"),
        "style_profile": str(card.get("style_profile", "") or project_style_profile or ""),
        "checks": checks,
        "forbidden_hits": forbidden_hits,
        "foreshadowing_planted": len(planted),
        "foreshadowing_visible": len(planted_hits),
    }


def _repeated_terms(text: str) -> list[dict[str, Any]]:
    compact = re.sub(r"[^\u4e00-\u9fff]", "", text)
    if len(compact) < 80:
        return []
    counter: Counter[str] = Counter()
    for size in (2, 3, 4):
        for idx in range(0, max(0, len(compact) - size + 1)):
            term = compact[idx : idx + size]
            if len(set(term)) == 1:
                continue
            counter[term] += 1
    rows = []
    for term, count in counter.most_common(20):
        if count >= 6 and term not in {"一个", "这个", "他们", "自己", "没有", "什么", "可以"}:
            rows.append({"term": term, "count": count})
    return rows[:8]


def _score_density(value: float, target: float, cap: int) -> float:
    if target <= 0:
        return 0.0
    return min(cap, safe_div(value, target) * cap)


def _craft_scores(metrics: dict[str, Any], hook_hits: list[str], style_profile: str = "", project_dir: str | Path | None = None) -> dict[str, int]:
    conflict_density = float(metrics.get("conflict_signal_density_per_1k", 0))
    agency_density = float(metrics.get("agency_signal_density_per_1k", 0))
    sensory_density = float(metrics.get("sensory_detail_density_per_1k", 0))
    body_density = float(metrics.get("body_emotion_density_per_1k", 0))
    intrigue_density = float(metrics.get("intrigue_signal_density_per_1k", 0))
    dialogue_ratio = float(metrics.get("dialogue_ratio", 0))
    sentence_var = float(metrics.get("sentence_length_stdev", 0))
    cliche_total = int(metrics.get("cliche_total", 0))

    page_turner = (
        _score_density(conflict_density, 4.0, 24)
        + _score_density(agency_density, 3.0, 20)
        + _score_density(intrigue_density, 3.0, 20)
        + min(18, len(hook_hits) * 4.5)
        + (18 if hook_hits else 0)
    )
    texture = (
        _score_density(sensory_density, 5.0, 24)
        + _score_density(body_density, 2.5, 18)
        + min(18, max(0, sentence_var - 4) * 2)
        + (18 if 0.08 <= dialogue_ratio <= 0.45 else 8 if dialogue_ratio <= 0.6 else 4)
        + max(0, 22 - cliche_total * 3)
    )
    profile = get_style_profile(style_profile, project_dir=project_dir)
    if profile:
        page_turner *= profile.page_turner_weight
        texture *= profile.texture_weight
    craft = page_turner * 0.55 + texture * 0.45
    return {
        "page_turner_score": int(round(max(0, min(100, page_turner)))),
        "prose_texture_score": int(round(max(0, min(100, texture)))),
        "reader_grip_score": int(round(max(0, min(100, craft)))),
    }


def _hook_window_score(text: str, opening: bool) -> dict[str, Any]:
    window = (text or "").strip()
    if not window:
        return {"score": 0, "terms": []}
    terms = OPENING_HOOK_TERMS if opening else HOOK_TERMS
    term_list = [term for term in terms if term in window]
    conflict_hits = term_hits(window, CONFLICT_TERMS)
    agency_hits = term_hits(window, AGENCY_TERMS)
    sensory_hits = term_hits(window, SENSORY_TERMS)
    intrigue_hits = term_hits(window, INTRIGUE_TERMS)
    exposition = exposition_sentence_ratio(split_sentences(window))
    score = (
        _score_density(conflict_hits, 2.0, 22)
        + _score_density(agency_hits, 1.0, 16)
        + _score_density(sensory_hits, 2.0, 18)
        + _score_density(intrigue_hits, 2.0, 22)
        + min(22, len(term_list) * 4)
    )
    if exposition > 0.55:
        score -= 12
    return {
        "score": int(round(max(0, min(100, score)))),
        "terms": term_list[:8],
        "conflict_hits": conflict_hits,
        "agency_hits": agency_hits,
        "sensory_hits": sensory_hits,
        "intrigue_hits": intrigue_hits,
        "exposition_ratio": round(exposition, 4),
    }


def build_polish_targets(chapter_text: str, limit: int = 8) -> list[dict[str, Any]]:
    paragraphs = [
        item.strip()
        for item in re.split(r"\n\s*\n+", chapter_text or "")
        if zh_count(item) > 0
    ]
    targets: list[dict[str, Any]] = []

    for idx, paragraph in enumerate(paragraphs, start=1):
        chars = zh_count(paragraph)
        sentences = split_sentences(paragraph)
        issues: list[str] = []
        actions: list[str] = []
        score = 0

        if idx == 1 and chars >= 50 and _hook_window_score(paragraph[:320], opening=True)["score"] < 40:
            score += 5
            issues.append("章首抓力弱")
            actions.append("开头前 300 字补出反常物件、信息缺口、人物选择或直接压力")
        if chars > 260:
            score += 4
            issues.append("长段落")
            actions.append("按动作、信息点和情绪转折拆段")
        if _has_cliche_hit(paragraph, _chapter_context_tags(paragraph)):
            score += 3
            issues.append("套话")
            actions.append("用具体动作、物件、停顿替换抽象反应")
        if len(sentences) >= 2 and exposition_sentence_ratio(sentences) > 0.4:
            score += 4
            issues.append("解释密集")
            actions.append("把背景和规则改成冲突中的发现、误会或对白交换")
        if chars >= 120 and term_hits(paragraph, CONFLICT_TERMS) == 0:
            score += 3
            issues.append("冲突弱")
            actions.append("补一个拒绝、追问、隐瞒、代价或必须选择")
        if chars >= 120 and term_hits(paragraph, SENSORY_TERMS) == 0:
            score += 2
            issues.append("可感细节少")
            actions.append("补一个能推动信息或情绪的物件、声音或触感")
        if chars >= 120 and term_hits(paragraph, BODY_EMOTION_TERMS) == 0:
            score += 1
            issues.append("身体反应少")
            actions.append("把情绪落到呼吸、手、喉咙、停顿或动作迟疑")
        if idx == len(paragraphs) and chars >= 50 and _hook_window_score(paragraph[-320:], opening=False)["score"] < 40:
            score += 5
            issues.append("章末余味弱")
            actions.append("把未解问题、危险信号、反常物件或人物选择压到最后一拍")

        if score:
            targets.append({
                "位置": f"段落 {idx}",
                "风险": score,
                "问题": "、".join(dict.fromkeys(issues)),
                "原文片段": _excerpt(paragraph),
                "改法": "；".join(dict.fromkeys(actions)),
            })

    targets.sort(key=lambda row: int(row["风险"]), reverse=True)
    if not targets and paragraphs:
        tail = paragraphs[-1]
        targets.append({
            "位置": f"段落 {len(paragraphs)}",
            "风险": 1,
            "问题": "章末余味复核",
            "原文片段": _excerpt(tail),
            "改法": "朗读检查最后一段是否仍有未解压力、人物选择或情绪余味",
        })
    return targets[:limit]


def polish_targets_to_assist_request(targets: list[dict[str, Any]], limit: int = 5) -> str:
    selected = targets[:limit]
    lines = [
        "请优先精修下面这些具体片段。",
        "只改这些片段代表的薄弱处，并把改法自然融入整章；保留剧情事实、人物关系、伏笔边界和 forbidden 约束。",
        "输出必须包含“## 建议”和“## 可直接采用文本”。",
        "",
        "## 重点精修片段",
    ]
    if not selected:
        lines.append("- 暂无明确薄弱片段，请做轻量文气和章末追读感微调。")
    for idx, row in enumerate(selected, start=1):
        lines.append(
            f"{idx}. {row.get('位置', '')}｜{row.get('问题', '')}\n"
            f"   原文片段：{row.get('原文片段', '')}\n"
            f"   改法：{row.get('改法', '')}"
        )
    return "\n".join(lines).strip()


def _excerpt(text: str, limit: int = 160) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


def _score_caveat(task_alignment: dict[str, Any]) -> str | None:
    chapter_mode = str(task_alignment.get("chapter_mode", "") or "").lower()
    pacing = str(task_alignment.get("pacing", "") or "").lower()
    style_profile = str(task_alignment.get("style_profile", "") or "")
    if chapter_mode in SLOW_CHAPTER_MODES:
        return f"参考分：本章为 {chapter_mode} 模式，冲突/主动性/追读类指标不参与扣分。"
    if pacing == "slow_burn":
        return "参考分：本章标注为 slow_burn，冲突/主动性/追读类指标不参与扣分。"
    if style_profile in INTERIOR_STYLE_PROFILES:
        return f"参考分：当前风格档案为 {style_profile}，冲突/主动性/追读类指标仅作观察。"
    return None


def _protected_finding(item: str, score_caveat: str | None) -> bool:
    return bool(score_caveat and item in PROTECTED_INTERIOR_ITEMS)


def _append_finding(
    findings: list[dict[str, str]],
    *,
    level: str,
    item: str,
    detail: str,
    score_caveat: str | None = None,
) -> None:
    if _protected_finding(item, score_caveat):
        findings.append({
            "level": "info",
            "item": item,
            "detail": f"{detail}（已降级：{score_caveat}）",
        })
    else:
        findings.append({"level": level, "item": item, "detail": detail})


def analyze_chapter_quality(
    project_dir: str | Path,
    chapter_num: int,
    chapter_text: str | None = None,
    source_markdown_path: str = "",
) -> dict[str, Any]:
    project_dir = Path(project_dir)
    if chapter_text is None:
        source_markdown_path, chapter_text = _latest_chapter_text(project_dir, chapter_num)
    if not chapter_text or not chapter_text.strip():
        raise FileNotFoundError(f"第{chapter_num:03d}章没有可诊断正文")

    sentences = split_sentences(chapter_text)
    sentence_lengths = [zh_count(sentence) for sentence in sentences]
    paragraphs = paragraph_lengths(chapter_text)
    dialogues = dialogue_segments(chapter_text)
    dialogue_chars = sum(zh_count(item) for item in dialogues)
    total_chars = zh_count(chapter_text)
    avg_sentence = safe_div(sum(sentence_lengths), len(sentence_lengths))
    sentence_stdev = stdev(sentence_lengths)
    repeated = _repeated_terms(chapter_text)
    opening = chapter_text[:320]
    tail = chapter_text[-320:]
    opening_hook = _hook_window_score(opening, opening=True)
    ending_hook = _hook_window_score(tail, opening=False)
    hook_hits = [term for term in HOOK_TERMS if term in tail]
    conflict_hits = term_hits(chapter_text, CONFLICT_TERMS)
    agency_hits = term_hits(chapter_text, AGENCY_TERMS)
    sensory_hits = term_hits(chapter_text, SENSORY_TERMS)
    body_emotion_hits = term_hits(chapter_text, BODY_EMOTION_TERMS)
    intrigue_hits = term_hits(chapter_text, INTRIGUE_TERMS)
    exposition_ratio = exposition_sentence_ratio(sentences)
    task_alignment = _task_card_alignment(project_dir, chapter_num, chapter_text)
    chapter_mode = str(task_alignment.get("chapter_mode", "plot") or "plot").lower()
    ending_style = str(task_alignment.get("ending_style", "hook") or "hook").lower()
    pacing = str(task_alignment.get("pacing", "normal") or "normal").lower()
    style_profile = str(task_alignment.get("style_profile", "") or "")
    thresholds = CHAPTER_MODE_THRESHOLDS.get(chapter_mode, CHAPTER_MODE_THRESHOLDS["plot"])
    context_tags = _chapter_context_tags(chapter_text, chapter_mode=chapter_mode, pacing=pacing)
    cliches = _cliche_hits(chapter_text, context_tags, style_profile, project_dir=project_dir)
    open_ending_hits = _open_ending_hits(tail)
    ending_signal_hits = hook_hits or (open_ending_hits if ending_style in {"open", "echo"} else [])
    if not thresholds.get("ending_required", True):
        ending_requirement_met = True
    else:
        ending_requirement_met = bool(hook_hits or open_ending_hits) if ending_style != "cliffhanger" else bool(hook_hits)
    score_caveat = _score_caveat(task_alignment)

    metrics = {
        "zh_chars": total_chars,
        "paragraphs": len(paragraphs),
        "sentences": len(sentences),
        "dialogue_turns": len(dialogues),
        "dialogue_ratio": round(safe_div(dialogue_chars, total_chars), 4),
        "avg_sentence_zh_chars": round(avg_sentence, 2),
        "sentence_length_stdev": round(sentence_stdev, 2),
        "long_sentences_over_80": sum(1 for value in sentence_lengths if value > 80),
        "long_paragraphs_over_260": sum(1 for value in paragraphs if value > 260),
        "cliche_total": sum(cliches.values()),
        "repeated_terms": repeated,
        "opening_hook_hits": opening_hook["terms"],
        "opening_hook_score": opening_hook["score"],
        "ending_hook_hits": hook_hits[:8],
        "ending_open_hits": open_ending_hits[:8],
        "ending_style": ending_style,
        "chapter_mode": chapter_mode,
        "pacing": pacing,
        "style_profile": style_profile,
        "chapter_mode_thresholds": thresholds,
        "ending_hook_score": ending_hook["score"],
        "conflict_signal_hits": conflict_hits,
        "conflict_signal_density_per_1k": round(safe_div(conflict_hits * 1000, total_chars), 2),
        "agency_signal_hits": agency_hits,
        "agency_signal_density_per_1k": round(safe_div(agency_hits * 1000, total_chars), 2),
        "sensory_detail_hits": sensory_hits,
        "sensory_detail_density_per_1k": round(safe_div(sensory_hits * 1000, total_chars), 2),
        "body_emotion_hits": body_emotion_hits,
        "body_emotion_density_per_1k": round(safe_div(body_emotion_hits * 1000, total_chars), 2),
        "intrigue_signal_hits": intrigue_hits,
        "intrigue_signal_density_per_1k": round(safe_div(intrigue_hits * 1000, total_chars), 2),
        "exposition_sentence_ratio": round(exposition_ratio, 4),
    }
    metrics.update(_craft_scores(metrics, ending_signal_hits, style_profile, project_dir=project_dir))

    findings: list[dict[str, str]] = []
    score = 100

    dialogue_min = float(thresholds.get("dialogue_min", 0.08))
    dialogue_max = float(thresholds.get("dialogue_max", 0.45))
    if metrics["dialogue_ratio"] < dialogue_min:
        if not _protected_finding("对白比例偏低", score_caveat):
            score -= 8
        _append_finding(
            findings,
            level="warning",
            item="对白比例偏低",
            detail=f"本章 {chapter_mode} 模式建议对白占比不低于 {dialogue_min:.0%}，当前可能偏说明或独白。",
            score_caveat=score_caveat,
        )
    elif metrics["dialogue_ratio"] > dialogue_max:
        score -= 8
        findings.append({"level": "warning", "item": "对白比例偏高", "detail": f"本章 {chapter_mode} 模式建议对白占比不高于 {dialogue_max:.0%}，当前可能缺少动作、场景压力和叙述推进。"})

    if avg_sentence > 55:
        score -= 10
        findings.append({"level": "warning", "item": "平均句长偏长", "detail": "长句过多会拖慢中快节奏，建议切分关键动作句。"})
    elif avg_sentence < 10 and len(sentences) >= 8:
        score -= 6
        findings.append({"level": "info", "item": "平均句长偏短", "detail": "短句密集会显得碎，可保留高压场景，平叙段适当合并。"})

    if sentence_stdev < 6 and len(sentences) >= 10:
        score -= 8
        findings.append({"level": "warning", "item": "句式节奏过平", "detail": "句长变化不足，容易产生机器式平滑感。"})

    if metrics["long_paragraphs_over_260"]:
        score -= min(12, metrics["long_paragraphs_over_260"] * 4)
        findings.append({"level": "warning", "item": "长段落过多", "detail": "移动端阅读会吃力，建议按动作、情绪转折或信息点拆段。"})

    if metrics["cliche_total"]:
        score -= min(18, metrics["cliche_total"] * 3)
        findings.append({"level": "warning", "item": "AI/网文化套话命中", "detail": "用具体动作、物件、停顿替换高频抽象表达。"})

    if total_chars >= 300 and metrics["opening_hook_score"] < 40:
        score -= 8
        findings.append({"level": "warning", "item": "章首抓力偏弱", "detail": "开头 320 字缺少反常物件、信息缺口、人物主动选择或直接压力。"})

    if not ending_requirement_met:
        score -= 10
        findings.append({"level": "warning", "item": "章末钩子偏弱", "detail": "末尾 320 字缺少疑问、反转、危险信号或下一章驱动力。"})

    if total_chars >= 300 and metrics["ending_hook_score"] < 40 and not open_ending_hits:
        score -= 8
        findings.append({"level": "warning", "item": "章末余味偏弱", "detail": "最后 320 字缺少未解压力、人物选择后果或下一章牵引。"})

    conflict_min = float(thresholds.get("conflict_min", 1.5))
    if total_chars >= 500 and metrics["conflict_signal_density_per_1k"] < conflict_min:
        if not _protected_finding("冲突信号偏弱", score_caveat):
            score -= 10
        _append_finding(
            findings,
            level="warning",
            item="冲突信号偏弱",
            detail="正文缺少可感知的阻力、代价、秘密或选择压力，容易像顺滑叙述而不是故事推进。",
            score_caveat=score_caveat,
        )

    if total_chars >= 500 and metrics["agency_signal_density_per_1k"] < 1.0:
        if not _protected_finding("角色主动性偏弱", score_caveat):
            score -= 8
        _append_finding(
            findings,
            level="warning",
            item="角色主动性偏弱",
            detail="角色很少做出选择、拒绝、试探或反击，建议让关键人物用行动推动局面。",
            score_caveat=score_caveat,
        )

    if total_chars >= 500 and metrics["sensory_detail_density_per_1k"] < 2.0:
        score -= 6
        findings.append({"level": "info", "item": "可感细节偏少", "detail": "缺少物件、声音、触感或空间细节，读者难以抓住场景质地。"})

    if total_chars >= 500 and metrics["body_emotion_density_per_1k"] < 0.8:
        score -= 5
        findings.append({"level": "info", "item": "情绪身体化偏弱", "detail": "情绪多停留在说明层，建议落到呼吸、手、喉咙、停顿或动作迟疑。"})

    if total_chars >= 500 and metrics["page_turner_score"] < 45:
        if not _protected_finding("追读张力偏弱", score_caveat):
            score -= 8
        _append_finding(
            findings,
            level="warning",
            item="追读张力偏弱",
            detail="冲突、异常线索、主动选择或章末驱动力不足，读者缺少继续翻页的理由。",
            score_caveat=score_caveat,
        )

    if total_chars >= 500 and metrics["prose_texture_score"] < 45:
        score -= 6
        findings.append({"level": "info", "item": "文气质地偏薄", "detail": "画面、身体反应、句式变化或潜台词不足，容易显得只是把情节讲完。"})

    if len(sentences) >= 8 and exposition_ratio > 0.35:
        score -= 8
        findings.append({"level": "warning", "item": "说明性句子偏多", "detail": "解释、规则或背景交代占比偏高，建议改成冲突中的发现、误解或交换。"})

    if task_alignment.get("forbidden_hits"):
        score -= min(30, 15 * len(task_alignment["forbidden_hits"]))
        findings.append({"level": "error", "item": "触碰任务卡禁止事项", "detail": "正文中出现任务卡 forbidden 项，正式定稿前应优先处理。"})

    uncovered = [check for check in task_alignment.get("checks", []) if check.get("covered") is False]
    if uncovered:
        score -= min(18, len(uncovered) * 6)
        findings.append({"level": "warning", "item": "任务卡对齐不足", "detail": "核心事件、情绪曲线或章末钩子没有在正文中形成可见落点。"})

    score = max(0, min(100, score))
    grade = _grade_for_score(score)

    report = {
        "version": VERSION,
        "chapter_number": chapter_num,
        "source_markdown_path": source_markdown_path,
        "score": score,
        "score_caveat": score_caveat,
        "grade": grade,
        "metrics": metrics,
        "cliches": cliches,
        "task_card_alignment": task_alignment,
        "findings": findings,
        "polish_targets": build_polish_targets(chapter_text),
        "created_at": now_iso(),
    }
    return apply_writer_overrides(report, read_writer_overrides(project_dir, chapter_num))


def render_quality_markdown(report: dict[str, Any]) -> str:
    metrics = report["metrics"]
    alignment = report["task_card_alignment"]
    findings = report["findings"]
    cliches = report["cliches"]
    repeated = metrics["repeated_terms"]
    polish_targets = report.get("polish_targets", [])

    lines = [
        f"# 第{report['chapter_number']:03d}章 章节质量诊断",
        "",
        f"- 评分：**{report['score']} / 100（{report['grade']}）**",
        *([f"- 评分说明：{report['score_caveat']}"] if report.get("score_caveat") else []),
        f"- 来源：`{report.get('source_markdown_path') or '未记录'}`",
        f"- 生成时间：{report['created_at']}",
        "",
        "## 核心指标",
        "",
        "| 指标 | 数值 |",
        "|------|------|",
        f"| 中文字数 | {metrics['zh_chars']} |",
        f"| 段落数 | {metrics['paragraphs']} |",
        f"| 句子数 | {metrics['sentences']} |",
        f"| 对白轮次 | {metrics['dialogue_turns']} |",
        f"| 对白占比 | {metrics['dialogue_ratio']:.1%} |",
        f"| 平均句长 | {metrics['avg_sentence_zh_chars']} 中文字 |",
        f"| 句长波动 | {metrics['sentence_length_stdev']} |",
        f"| 80 字以上长句 | {metrics['long_sentences_over_80']} |",
        f"| 260 字以上长段 | {metrics['long_paragraphs_over_260']} |",
        f"| 套话命中 | {metrics['cliche_total']} |",
        f"| 冲突信号密度 | {metrics['conflict_signal_density_per_1k']} / 千字 |",
        f"| 主动性信号密度 | {metrics['agency_signal_density_per_1k']} / 千字 |",
        f"| 可感细节密度 | {metrics['sensory_detail_density_per_1k']} / 千字 |",
        f"| 说明性句子占比 | {metrics['exposition_sentence_ratio']:.1%} |",
        f"| 章首抓力 | {metrics['opening_hook_score']} / 100 |",
        f"| 章末余味 | {metrics['ending_hook_score']} / 100 |",
        f"| 追读张力 | {metrics['page_turner_score']} / 100 |",
        f"| 文气质地 | {metrics['prose_texture_score']} / 100 |",
        f"| 读者抓力 | {metrics['reader_grip_score']} / 100 |",
        "",
        "## 好看度雷达",
        "",
        "| 维度 | 数值 | 读法 |",
        "|------|------|------|",
        f"| 章首抓力 | {metrics['opening_hook_score']} / 100 | 开头是否有反常物件、信息缺口、人物选择或压力 |",
        f"| 章末余味 | {metrics['ending_hook_score']} / 100 | 结尾是否留下未解压力、后果或下一章牵引 |",
        f"| 追读张力 | {metrics['page_turner_score']} / 100 | 冲突、异常线索、角色选择和章末驱动力 |",
        f"| 文气质地 | {metrics['prose_texture_score']} / 100 | 可感细节、身体化情绪、句式变化和套话控制 |",
        f"| 读者抓力 | {metrics['reader_grip_score']} / 100 | 综合衡量这一章是否让人想继续读 |",
        f"| 身体化情绪密度 | {metrics['body_emotion_density_per_1k']} / 千字 | 情绪是否落到动作与生理反应 |",
        f"| 异常/线索密度 | {metrics['intrigue_signal_density_per_1k']} / 千字 | 类型钩子和信息牵引是否可感 |",
        "",
        "## 重点精修片段",
        "",
    ]
    if polish_targets:
        lines += [
            "| 位置 | 问题 | 改法 | 原文片段 |",
            "|------|------|------|----------|",
        ]
        for row in polish_targets:
            lines.append(
                f"| {_md_cell(row.get('位置', ''))} | {_md_cell(row.get('问题', ''))} | "
                f"{_md_cell(row.get('改法', ''))} | {_md_cell(row.get('原文片段', ''))} |"
            )
    else:
        lines.append("- 暂无明确薄弱片段。")

    lines += [
        "",
        "## 诊断发现",
        "",
    ]
    if findings:
        for item in findings:
            level = item.get("level", "")
            action = item.get("writer_action", "")
            if level == "accepted_by_writer":
                action_label = "作家已保护此建议" if action == "protect" else "作家已拒绝此建议"
                lines.append(
                    f"- **{item['item']}**：{action_label}。理由：{item.get('writer_reason', '')}"
                )
            elif level == "rebutted_by_writer":
                lines.append(
                    f"- **{item['item']}**：作家已反驳此诊断。理由：{item.get('writer_reason', '')}"
                )
            elif action == "adopt":
                lines.append(
                    f"- **{item['item']}**：作家已采纳，将在下次改稿执行。备注：{item.get('writer_reason', '')}"
                )
            else:
                lines.append(f"- **{item['item']}**：{item['detail']}")
    else:
        lines.append("- 未发现明显节奏、套话、任务卡对齐或章末钩子风险。")

    if report.get("writer_overrides"):
        lines.extend(["", "## 作家豁免", ""])
        for item in report.get("writer_overrides", []):
            lines.append(f"- {item.get('rejected_advice', '')}：{item.get('writer_reason', '')}")

    lines += ["", "## 任务卡对齐", ""]
    if not alignment.get("available"):
        lines.append(f"- 未找到任务卡：`{alignment.get('task_card_path', '')}`")
    else:
        lines.append(f"- 任务卡状态：{alignment.get('status') or '未记录'}")
        for check in alignment.get("checks", []):
            state = "已覆盖" if check.get("covered") else "需核对"
            lines.append(f"- {check['label']}：{state}")
        if alignment.get("forbidden_hits"):
            lines.append("- 禁止事项命中：" + "、".join(alignment["forbidden_hits"]))
        planted = alignment.get("foreshadowing_planted", 0)
        if planted:
            visible = alignment.get("foreshadowing_visible", 0)
            lines.append(f"- 伏笔可见度：{visible}/{planted}")

    lines += ["", "## 套话与重复", ""]
    if cliches:
        lines.append("- 套话：" + "、".join(f"{k}×{v}" for k, v in cliches.items()))
    else:
        lines.append("- 未命中内置高频套话表。")
    if repeated:
        lines.append("- 高频重复片段：" + "、".join(f"{row['term']}×{row['count']}" for row in repeated))
    else:
        lines.append("- 未发现明显高频重复片段。")

    lines += ["", "## 改稿优先级", ""]
    if findings:
        lines.append("1. 先处理 error/warning 项，尤其是任务卡禁止事项和章末钩子。")
        lines.append("2. 再调节句长与段落长度，让动作、对白和信息释放交替推进。")
        lines.append("3. 最后替换套话，把抽象情绪落到动作、物件、停顿和潜台词。")
    else:
        lines.append("1. 可进入人工精修，重点朗读对白区分度和章节末尾追读感。")
    return "\n".join(lines).strip() + "\n"


def quality_needs_revision(report: dict[str, Any], threshold: int = 78) -> bool:
    if int(report.get("score", 100)) < threshold:
        return True
    findings = _active_findings(report.get("findings", []))
    if any(item.get("level") == "error" for item in findings):
        return True
    risky_items = {"章末钩子偏弱", "任务卡对齐不足", "触碰任务卡禁止事项"}
    return any(item.get("item") in risky_items for item in findings)


CHECKLIST_ACTIONS = {
    "触碰任务卡禁止事项": (
        "删除、替换或延后 forbidden 信息，把已经泄露的事实改成误导、遮蔽或人物误判。",
        "正文不再直接出现 forbidden 命中词，读者只能获得可疑信号，不能获得答案。",
    ),
    "任务卡对齐不足": (
        "补出任务卡核心事件、情绪曲线或章末钩子的可见落点，让它进入行动、对白或场景结果。",
        "读者能从正文中直接看见任务卡目标，而不是只在章纲里成立。",
    ),
    "章末钩子偏弱": (
        "重写末尾 200-400 字，把新问题、危险信号、反常物件或人物选择压到最后一拍。",
        "结尾留下明确的下一章阅读理由，并且不提前解释答案。",
    ),
    "追读张力偏弱": (
        "在关键场景加入阻力、代价、异常线索和角色主动选择，避免顺滑讲完事件。",
        "至少一个场景出现必须处理的麻烦，章末仍保留未解压力。",
    ),
    "冲突信号偏弱": (
        "把解释性推进改成可对抗的推进：有人拒绝、隐瞒、逼问、交换或付出代价。",
        "每个关键段落都有阻力、代价、选择压力中的至少一种。",
    ),
    "角色主动性偏弱": (
        "让视角人物主动选择、试探、拒绝、撒谎、追问或反击，而不是等待信息到来。",
        "关键转折由角色行动触发，不由旁白或巧合送达。",
    ),
    "文气质地偏薄": (
        "补具体物件、声音、触感、空间压力和潜台词，用动作承载情绪。",
        "读者能记住至少一个场景物件和一处人物身体反应。",
    ),
    "可感细节偏少": (
        "给重要动作配一个物件、声音或触感，让场景有可抓住的现实支点。",
        "每个主要场景至少有一个推动信息或情绪的具体细节。",
    ),
    "情绪身体化偏弱": (
        "把抽象情绪落到喉咙、手、呼吸、停顿、迟疑或失控的小动作上。",
        "人物情绪不用解释也能从身体反应和动作节奏中读出来。",
    ),
    "说明性句子偏多": (
        "把背景、规则和因果解释拆进发现、误会、对话交锋或行动后果里。",
        "至少一半解释句被改成场景内的信息交换或冲突结果。",
    ),
    "AI/网文化套话命中": (
        "删除套话，用更具体的动作、物件、停顿和感官变化替换抽象反应。",
        "命中的套话表达消失，保留情绪但换成独特场景细节。",
    ),
    "句式节奏过平": (
        "按动作、观察、对白、内心反应交替重排句子，拉开长短句节奏。",
        "同一段内不连续使用相似长度和相似结构的句子。",
    ),
    "平均句长偏长": (
        "切开承载多个动作或解释的长句，把关键动作单独成句。",
        "高压段落读起来更利落，长句只保留在需要铺陈的地方。",
    ),
    "长段落过多": (
        "按动作转折、信息点、情绪变化拆段，给移动端阅读留出呼吸。",
        "长段落被拆成更清楚的推进单位，段落之间有节奏变化。",
    ),
    "对白比例偏低": (
        "补一场带信息差的对白，让人物通过追问、回避或试探交换信息。",
        "对白不闲聊，每轮都改变关系、信息或压力。",
    ),
    "对白比例偏高": (
        "在对白之间补动作、场景压力和人物观察，避免只剩台词推进。",
        "读者能看见说话时发生了什么，而不是只听见解释。",
    ),
    "章首抓力偏弱": (
        "重写开头 200-400 字，用反常物件、信息缺口、人物选择或直接压力把读者拉进场。",
        "第一屏就出现可追问的问题或可感压力，而不是平铺背景。",
    ),
    "章末余味偏弱": (
        "重写最后 200-400 字，把选择后果、未解压力或反常信号留在最后一拍。",
        "读者能明确知道下一章还要追什么，同时没有提前解释答案。",
    ),
}


def build_revision_checklist(report: dict[str, Any], limit: int = 10) -> list[dict[str, Any]]:
    metrics = report.get("metrics", {})
    alignment = report.get("task_card_alignment", {})
    findings = _active_findings(report.get("findings", []))
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(priority: int, area: str, issue: str, action: str, acceptance: str, evidence: str = "") -> None:
        key = f"{area}:{issue}:{evidence}"
        if key in seen:
            return
        seen.add(key)
        rows.append({
            "优先级": f"P{priority}",
            "维度": area,
            "问题": issue,
            "改法": action,
            "验收标准": acceptance,
            "证据": evidence,
        })

    if alignment.get("forbidden_hits"):
        hits = "、".join(alignment.get("forbidden_hits", []))
        action, acceptance = CHECKLIST_ACTIONS["触碰任务卡禁止事项"]
        add(0, "任务卡", "触碰任务卡禁止事项", action, acceptance, hits)

    for check in alignment.get("checks", []):
        if check.get("covered") is False:
            label = check.get("label", check.get("field", "任务卡字段"))
            action, acceptance = CHECKLIST_ACTIONS["任务卡对齐不足"]
            add(1, "任务卡", f"补齐{label}", action, acceptance, str(check.get("value", "")))

    planted = int(alignment.get("foreshadowing_planted", 0) or 0)
    visible = int(alignment.get("foreshadowing_visible", 0) or 0)
    if planted and visible < planted:
        add(
            2,
            "伏笔",
            "伏笔可见度不足",
            "把伏笔落成具体物件、异样反应或信息缺口，避免只在章纲里存在。",
            "读者能注意到异常，但无法直接得到答案。",
            f"{visible}/{planted}",
        )

    for item in findings:
        issue = str(item.get("item", "问题"))
        action, acceptance = CHECKLIST_ACTIONS.get(
            issue,
            ("按诊断描述做局部改写，优先保留剧情事实和人物关系。", "对应诊断项不再明显成立。"),
        )
        level = item.get("level", "warning")
        priority = 0 if level == "error" else 2 if level == "info" else 1
        area = _checklist_area(issue)
        add(priority, area, issue, action, acceptance, str(item.get("detail", "")))

    if float(metrics.get("opening_hook_score", 100) or 0) < 55:
        action, acceptance = CHECKLIST_ACTIONS["章首抓力偏弱"]
        add(1, "好看度", "章首抓力偏弱", action, acceptance, f"{metrics.get('opening_hook_score', 0)} / 100")
    if float(metrics.get("ending_hook_score", 100) or 0) < 55:
        action, acceptance = CHECKLIST_ACTIONS["章末余味偏弱"]
        add(1, "好看度", "章末余味偏弱", action, acceptance, f"{metrics.get('ending_hook_score', 0)} / 100")
    if float(metrics.get("page_turner_score", 100) or 0) < 55:
        action, acceptance = CHECKLIST_ACTIONS["追读张力偏弱"]
        add(1, "好看度", "追读张力偏弱", action, acceptance, f"{metrics.get('page_turner_score', 0)} / 100")
    if float(metrics.get("prose_texture_score", 100) or 0) < 55:
        action, acceptance = CHECKLIST_ACTIONS["文气质地偏薄"]
        add(2, "好看度", "文气质地偏薄", action, acceptance, f"{metrics.get('prose_texture_score', 0)} / 100")
    if float(metrics.get("exposition_sentence_ratio", 0) or 0) > 0.35:
        action, acceptance = CHECKLIST_ACTIONS["说明性句子偏多"]
        add(1, "信息释放", "说明性句子偏多", action, acceptance, f"{float(metrics.get('exposition_sentence_ratio', 0)):.1%}")
    if int(metrics.get("cliche_total", 0) or 0) > 0:
        action, acceptance = CHECKLIST_ACTIONS["AI/网文化套话命中"]
        cliches = report.get("cliches", {})
        add(2, "语言", "AI/网文化套话命中", action, acceptance, "、".join(f"{k}×{v}" for k, v in cliches.items()))

    if not rows:
        add(
            3,
            "精修",
            "人工朗读微调",
            "保留现有结构，重点检查对白区分度、段尾余味和章末追读感。",
            "朗读时没有顺滑但空泛的句子，最后一段仍有牵引力。",
            f"{report.get('score', 0)} / 100",
        )

    rows.sort(key=lambda row: (int(str(row["优先级"]).lstrip("P") or 9), _area_order(row["维度"])))
    return rows[:limit]


def render_revision_checklist_markdown(report: dict[str, Any], limit: int = 10) -> str:
    rows = build_revision_checklist(report, limit=limit)
    lines = [
        f"# 第{int(report.get('chapter_number', 0)):03d}章 改稿清单",
        "",
        f"- 来源：`{report.get('source_markdown_path') or '未记录'}`",
        f"- 质量评分：{report.get('score', 0)} / 100（{report.get('grade', '未评级')}）",
        "",
        "| 优先级 | 维度 | 问题 | 改法 | 验收标准 | 证据 |",
        "|--------|------|------|------|----------|------|",
    ]
    for row in rows:
        lines.append(
            "| {priority} | {area} | {issue} | {action} | {acceptance} | {evidence} |".format(
                priority=_md_cell(row["优先级"]),
                area=_md_cell(row["维度"]),
                issue=_md_cell(row["问题"]),
                action=_md_cell(row["改法"]),
                acceptance=_md_cell(row["验收标准"]),
                evidence=_md_cell(row.get("证据", "")),
            )
        )
    lines += ["", "## 给 AI 辅助的指令", "", checklist_to_assist_request(rows)]
    return "\n".join(lines).strip() + "\n"


def checklist_to_assist_request(checklist: list[dict[str, Any]], limit: int = 6) -> str:
    selected = checklist[:limit]
    lines = [
        "请严格按下面改稿清单做一轮可采纳的好看度精修。",
        "优先处理 P0/P1；保留核心剧情、人物关系和既有伏笔，不新增硬设定，不提前揭露 forbidden。",
        "输出必须包含“## 建议”和“## 可直接采用文本”。",
        "",
        "## 改稿清单",
    ]
    for idx, row in enumerate(selected, start=1):
        lines.append(
            f"{idx}. [{row.get('优先级', '')}] {row.get('维度', '')}｜{row.get('问题', '')}\n"
            f"   改法：{row.get('改法', '')}\n"
            f"   验收：{row.get('验收标准', '')}"
        )
    return "\n".join(lines).strip()


def merge_revision_requests(checklist: list[dict[str, Any]], polish_targets: list[dict[str, Any]]) -> str:
    parts = [checklist_to_assist_request(checklist)]
    if polish_targets:
        parts.append(polish_targets_to_assist_request(polish_targets))
    return "\n\n".join(part for part in parts if part.strip())


def write_revision_checklist(
    project_dir: str | Path,
    chapter_num: int,
    report: dict[str, Any] | None = None,
    chapter_text: str | None = None,
    source_markdown_path: str = "",
) -> Path:
    project_dir = Path(project_dir)
    if report is None:
        report = analyze_chapter_quality(project_dir, chapter_num, chapter_text, source_markdown_path)
    ch = f"{chapter_num:03d}"
    md_path = project_dir / "04_审核日志" / f"第{ch}章_改稿清单.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_revision_checklist_markdown(report), encoding="utf-8")
    return md_path


def _checklist_area(issue: str) -> str:
    if "任务卡" in issue or "禁止" in issue:
        return "任务卡"
    if "钩子" in issue or "追读" in issue or "冲突" in issue or "主动性" in issue or "章首" in issue or "章末" in issue:
        return "好看度"
    if "说明" in issue:
        return "信息释放"
    if "套话" in issue or "句" in issue or "段落" in issue or "对白" in issue:
        return "语言"
    if "细节" in issue or "情绪" in issue or "质地" in issue:
        return "质地"
    return "综合"


def _area_order(area: str) -> int:
    order = {"任务卡": 0, "好看度": 1, "信息释放": 2, "伏笔": 3, "质地": 4, "语言": 5}
    return order.get(area, 9)


def _md_cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def render_revision_brief(report: dict[str, Any], threshold: int = 78) -> str:
    metrics = report.get("metrics", {})
    alignment = report.get("task_card_alignment", {})
    findings = _active_findings(report.get("findings", []))
    lines = [
        f"## 质量诊断改稿指令（V1.9）",
        f"- 当前评分：{report.get('score', 0)} / 100（{report.get('grade', '未评级')}），目标不低于 {threshold}。",
        *([f"- 评分说明：{report.get('score_caveat')}"] if report.get("score_caveat") else []),
        f"- 对白占比：{float(metrics.get('dialogue_ratio', 0)):.1%}；平均句长：{metrics.get('avg_sentence_zh_chars', 0)}；句长波动：{metrics.get('sentence_length_stdev', 0)}。",
        f"- 长句：{metrics.get('long_sentences_over_80', 0)}；长段：{metrics.get('long_paragraphs_over_260', 0)}；套话命中：{metrics.get('cliche_total', 0)}。",
        f"- 冲突信号：{metrics.get('conflict_signal_density_per_1k', 0)} / 千字；主动性信号：{metrics.get('agency_signal_density_per_1k', 0)} / 千字；说明性句子：{float(metrics.get('exposition_sentence_ratio', 0)):.1%}。",
        f"- 首尾钩子：章首抓力 {metrics.get('opening_hook_score', 0)} / 100；章末余味 {metrics.get('ending_hook_score', 0)} / 100。",
        f"- 好看度雷达：追读张力 {metrics.get('page_turner_score', 0)} / 100；文气质地 {metrics.get('prose_texture_score', 0)} / 100；读者抓力 {metrics.get('reader_grip_score', 0)} / 100。",
        "",
        "### 必须处理",
    ]
    if findings:
        for item in findings:
            lines.append(f"- {item.get('item', '问题')}：{item.get('detail', '')}")
    else:
        lines.append("- 未发现硬性问题，保持既有剧情，仅做细部润色。")

    reservations = report.get("writer_overrides", [])
    if reservations:
        lines += ["", "### 作家已保护/拒绝的诊断（禁止执行）"]
        for item in reservations:
            lines.append(f"- 不要执行「{item.get('rejected_advice', '')}」；作家理由：{item.get('writer_reason', '')}")

    if alignment.get("available"):
        lines += ["", "### 任务卡对齐"]
        for check in alignment.get("checks", []):
            state = "已覆盖" if check.get("covered") else "需强化"
            lines.append(f"- {check.get('label', check.get('field', '字段'))}：{state}。目标：{check.get('value', '')}")
        if alignment.get("forbidden_hits"):
            lines.append("- 必须删除或改写 forbidden 命中：" + "、".join(alignment["forbidden_hits"]))
        planted = alignment.get("foreshadowing_planted", 0)
        if planted:
            lines.append(f"- 伏笔可见度：{alignment.get('foreshadowing_visible', 0)}/{planted}，必要时补出更自然的伏笔落点。")

    cliches = report.get("cliches", {})
    repeated = metrics.get("repeated_terms", [])
    if cliches or repeated:
        lines += ["", "### 语言层改写"]
        if cliches:
            lines.append("- 替换套话：" + "、".join(f"{k}×{v}" for k, v in cliches.items()))
        if repeated:
            lines.append("- 降低重复：" + "、".join(f"{row.get('term')}×{row.get('count')}" for row in repeated[:6]))

    lines += [
        "",
        "### 改稿约束",
        "- 不新增与章纲、任务卡、世界观冲突的事实。",
        "- 不提前揭露任务卡禁止事项。",
        "- 保留本章核心事件和人物关系推进，只修节奏、信息释放、对白张力和章末追读感。",
    ]
    return "\n".join(lines).strip()


def write_quality_diagnostics(
    project_dir: str | Path,
    chapter_num: int,
    chapter_text: str | None = None,
    source_markdown_path: str = "",
) -> tuple[Path, Path, dict[str, Any]]:
    project_dir = Path(project_dir)
    report = analyze_chapter_quality(project_dir, chapter_num, chapter_text, source_markdown_path)
    ch = f"{chapter_num:03d}"
    md_path = project_dir / "04_审核日志" / f"第{ch}章_质量诊断.md"
    json_path = project_dir / "04_审核日志" / f"第{ch}章_质量诊断.json"
    checklist_path = project_dir / "04_审核日志" / f"第{ch}章_改稿清单.md"
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_quality_markdown(report), encoding="utf-8")
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    checklist_path.write_text(render_revision_checklist_markdown(report), encoding="utf-8")
    return md_path, json_path, report
