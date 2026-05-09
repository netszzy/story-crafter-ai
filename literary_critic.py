"""
V5.0-beta2 文学批评层。

它和质量/戏剧诊断并行存在：不打分、不制造必改项，只观察可被记住的
瞬间、未说之语、自我欺骗和工程诊断可能误伤的文学性。
"""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from llm_router import LLMRouter
from project_archive import archive_existing
from novel_schemas import LiteraryView, MemorableMoment, model_to_json
from prompt_assembly import build_axis_context


PROMPT_REL = "prompts/文学批评.md"
MEMORABLE_TERMS = ["被压扁的眼睛", "旧钥匙", "水声", "信封", "抽屉", "伞尖", "空床", "灯熄"]
UNSAID_TERMS = ["没有", "不说", "沉默", "流程", "藏", "遮住", "退后", "停在", "没说"]
MORAL_TERMS = ["不该", "秘密", "误判", "背叛", "亏欠", "债", "旧案", "真相"]
SELF_DECEPTION_TERMS = ["流程", "规矩", "没事", "应该", "习惯", "只是", "没有立刻", "正常"]
PROTECTED_MODE_TERMS = ["沉默", "流程", "没有立刻", "退后", "看着", "窗", "雨", "信封", "眼睛"]


def analyze_literary_view(
    project_dir: Path,
    chapter_num: int,
    chapter_text: str,
    task_card_json: str = "",
    llm: LLMRouter | None = None,
) -> LiteraryView:
    """返回本章 LiteraryView。Mock 模式只做启发式占位，并明确标注。"""
    project_dir = Path(project_dir)
    llm = llm or LLMRouter(project_dir=project_dir)
    if _should_mock(llm):
        view = _mock_literary_view(chapter_num, chapter_text)
        view.provider_used = "mock"
        view.model_used = "mock-literary-critic"
        return view

    system_prompt = _build_system_prompt(project_dir)
    user_msg = _build_user_msg(chapter_text, task_card_json)
    raw = llm.critic_text(
        system_prompt=system_prompt,
        user_prompt=user_msg,
        workflow="literary-critic",
        role="literary-critic",
        max_tokens=3000,
    )
    return _parse_response(raw, chapter_num, llm, project_dir=project_dir, fallback_text=chapter_text)


def write_literary_view(project_dir: Path, view: LiteraryView) -> tuple[Path, Path]:
    """写入 04_审核日志/第NNN章_文学批评.json + .md。"""
    project_dir = Path(project_dir)
    ch = f"{view.chapter_number:03d}"
    log_dir = project_dir / "04_审核日志"
    json_path = log_dir / f"第{ch}章_文学批评.json"
    md_path = log_dir / f"第{ch}章_文学批评.md"
    log_dir.mkdir(parents=True, exist_ok=True)
    archive_existing(json_path)
    archive_existing(md_path)
    json_path.write_text(model_to_json(view) + "\n", encoding="utf-8")
    md_path.write_text(literary_view_to_markdown(view), encoding="utf-8")
    return md_path, json_path


def read_literary_view(project_dir: Path, chapter_num: int) -> LiteraryView | None:
    path = Path(project_dir) / "04_审核日志" / f"第{chapter_num:03d}章_文学批评.json"
    if not path.exists():
        return None
    try:
        return LiteraryView.model_validate(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValidationError):
        return None


def literary_view_to_markdown(view: LiteraryView) -> str:
    lines = [
        f"# 第{view.chapter_number:03d}章 文学批评",
        "",
        f"- 模型：{view.provider_used}/{view.model_used}",
        f"- Mock：{'是' if view.is_mock else '否'}",
        f"- 不可量化保护：{'是' if view.cannot_be_quantified else '否'}",
        "",
        "## 可被记住的瞬间",
    ]
    if view.memorable_moments:
        for item in view.memorable_moments:
            lines += [
                f"### {item.quote or '未标注原文'}",
                f"- 为什么留下来：{item.why_memorable}",
                f"- 脆弱处：{item.fragility}",
            ]
    else:
        lines.append("- 暂未识别。")

    for title, values in [
        ("未说之语", view.unsaid_tension),
        ("道德灰度", view.moral_ambiguity),
        ("自我欺骗", view.self_deception_signals),
        ("读者残响", view.reader_residue),
        ("文学风险", view.literary_risks),
    ]:
        lines += ["", f"## {title}"]
        if values:
            lines.extend(f"- {item}" for item in values)
        else:
            lines.append("- 暂无。")
    return "\n".join(lines).strip() + "\n"


def _build_system_prompt(project_dir: Path) -> str:
    template_path = Path(project_dir) / PROMPT_REL
    if not template_path.exists():
        template_path = Path(__file__).resolve().parent / PROMPT_REL
    template = template_path.read_text(encoding="utf-8") if template_path.exists() else ""
    schema = json.dumps(LiteraryView.model_json_schema(), ensure_ascii=False, indent=2)
    return (
        template.replace("{{ axis_context }}", build_axis_context(project_dir) or "（项目轴为空，按正文和任务卡阅读）")
        .replace("{{ json_schema }}", schema)
        .strip()
    )


def _build_user_msg(chapter_text: str, task_card_json: str = "") -> str:
    return "\n\n".join([
        "## 章节任务卡\n\n" + (task_card_json.strip() or "（未提供）"),
        "## 本章正文\n\n" + chapter_text.strip(),
    ])


def _parse_response(
    raw: str,
    chapter_num: int,
    llm: LLMRouter | None = None,
    project_dir: Path | None = None,
    fallback_text: str = "",
) -> LiteraryView:
    try:
        payload = _extract_json_object(raw)
        data = json.loads(payload)
        data.setdefault("chapter_number", chapter_num)
        if llm is not None:
            data.setdefault("provider_used", getattr(llm, "CRITIC_PROVIDER", ""))
            data.setdefault("model_used", _critic_model_name(llm))
        return LiteraryView.model_validate(data)
    except (ValueError, json.JSONDecodeError, ValidationError) as exc:
        if project_dir is not None:
            _log_parse_failure(project_dir, chapter_num, raw, exc)
        view = _mock_literary_view(chapter_num, fallback_text or raw)
        view.provider_used = "mock"
        view.model_used = "mock-literary-critic"
        return view


def _mock_literary_view(chapter_num: int, text: str) -> LiteraryView:
    """离线占位：只做启发式抽样，明确不冒充真实文学批评。"""
    title = _extract_title(text)
    moments = _mock_memorable_moments(text)
    unsaid = _mock_lines(text, UNSAID_TERMS, "这一处把压力留在未说出口的位置。")
    ambiguity = _mock_lines(text, MORAL_TERMS, "这一处保留了无法立刻判定对错的灰度。")
    self_deception = _mock_lines(text, SELF_DECEPTION_TERMS, "人物可能正在用秩序或习惯遮住真实判断。")
    residue = [
        "[Mock] 未调用真实文学批评模型；以下只用于离线验收，不代表最终文学判断。"
    ]
    if moments:
        residue.append(f"最容易留下来的意象是「{moments[0].quote}」。")

    cannot = bool(moments) or any(term in text for term in PROTECTED_MODE_TERMS)
    risks = [
        "[Mock] 不应把本占位结果当作真实文学评估。",
    ]
    if cannot:
        risks.append("若为了抬高工程指标而强行增加冲突、动作或身体情绪，可能破坏本章的克制、氛围和未说之语。")

    return LiteraryView(
        chapter_number=chapter_num,
        title=title,
        model_used="mock-literary-critic",
        provider_used="mock",
        memorable_moments=moments,
        unsaid_tension=unsaid,
        moral_ambiguity=ambiguity,
        self_deception_signals=self_deception,
        reader_residue=residue,
        literary_risks=risks,
        cannot_be_quantified=cannot,
        is_mock=True,
    )


def _mock_memorable_moments(text: str) -> list[MemorableMoment]:
    moments: list[MemorableMoment] = []
    for term in MEMORABLE_TERMS:
        if term in text:
            moments.append(MemorableMoment(
                quote=_excerpt_around(text, term, 36),
                why_memorable="物件和意象承担了未解释的情绪，让读者先记住画面。",
                fragility="它的力量来自克制；解释过多或补成外显冲突会变钝。",
            ))
        if len(moments) >= 3:
            break
    if not moments:
        paragraphs = _paragraphs(text)
        for paragraph in paragraphs[:2]:
            if any(mark in paragraph for mark in ["像", "仿佛", "雨", "灯", "窗", "信"]):
                moments.append(MemorableMoment(
                    quote=_clip(paragraph, 80),
                    why_memorable="这一段有可见物件或比喻，可能成为读者的记忆锚点。",
                    fragility="仍需真实批评模型确认，mock 不判断文学成色。",
                ))
                break
    return moments


def _mock_lines(text: str, terms: list[str], suffix: str) -> list[str]:
    lines: list[str] = []
    for term in terms:
        if term in text:
            lines.append(f"「{_excerpt_around(text, term, 32)}」：{suffix}")
        if len(lines) >= 3:
            break
    return lines


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
        raise ValueError("No JSON object found in literary critic response")
    return text[start : end + 1]


def _log_parse_failure(project_dir: Path, chapter_num: int, raw: str, exc: Exception) -> Path:
    log_dir = Path(project_dir) / "logs" / "literary_critic_failures"
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"第{chapter_num:03d}章_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    path.write_text(f"{type(exc).__name__}: {exc}\n\n{raw}", encoding="utf-8")
    return path


def _critic_model_name(llm: LLMRouter) -> str:
    provider = str(getattr(llm, "CRITIC_PROVIDER", "deepseek")).lower()
    if provider == "openrouter":
        return str(getattr(llm, "OPENROUTER_CRITIC_MODEL", ""))
    return str(getattr(llm, "DEEPSEEK_MODEL", ""))


def _paragraphs(text: str) -> list[str]:
    items = re.split(r"\n\s*\n+", (text or "").strip())
    if len(items) <= 1:
        items = [line for line in (text or "").splitlines() if line.strip()]
    return [" ".join(item.strip().split()) for item in items if _zh_count(item) >= 8 and not item.strip().startswith("#")]


def _extract_title(text: str) -> str:
    match = re.search(r"(?m)^#\s*(.+)$", text or "")
    return match.group(1).strip() if match else ""


def _excerpt_around(text: str, term: str, radius: int = 32) -> str:
    compact = " ".join((text or "").split())
    idx = compact.find(term)
    if idx < 0:
        return term
    start = max(0, idx - radius)
    end = min(len(compact), idx + len(term) + radius)
    excerpt = compact[start:end].strip()
    return excerpt if len(excerpt) <= radius * 2 + len(term) else _clip(excerpt, radius * 2 + len(term))


def _clip(text: str, limit: int) -> str:
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit].rstrip() + "..."


def _zh_count(text: str) -> int:
    return sum(1 for char in text if "\u4e00" <= char <= "\u9fff")
