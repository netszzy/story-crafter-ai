"""
V4.0 Phase B —— sheng yin zhi wen zhen duan。

chun ben di zheng ze fen xi（ling API cheng ben）：ti qu mei jiao se dui bai，ji suan ju chang、gao pin ci、
yu qi ci pin lu、fan wen bi li，xiang si du > 70% biao ji jing gao。
"""

from __future__ import annotations

import json
import re
from collections import Counter
from math import sqrt
from pathlib import Path

from novel_schemas import (
    CharacterVoiceProfile,
    VoiceFingerprint,
    model_to_json,
    write_json_model,
)

# “ = "  ” = "
LQ = "“"
RQ = "”"
DIALOGUE_VERBS = "道|说|问|喊|叫|嚷|吼|答|回|应|叹|笑|哭|骂|喝|劝|斥|喝问|低语|开口|出声"
SENTENCE_END = re.compile(r"[。！？!\?.…]")
PARTICLES = {"呢", "吧", "啊", "嘛", "呀", "呗", "啦", "哦", "欸", "喂", "嗯", "呵"}
PUNCT_CLEAN = re.compile(r"[「」" + LQ + RQ + r"‘’《》()（）\s]+")


def extract_dialogue_by_character(text: str, known_names: list[str] | None = None) -> dict[str, list[str]]:
    if not known_names:
        known_names = _detect_names_from_text(text)

    result: dict[str, list[str]] = {}
    if not known_names:
        return result

    name_alt = "|".join(re.escape(n) for n in known_names)
    pattern = re.compile(
        rf"({name_alt})(.{{0,8}}?)({DIALOGUE_VERBS})(.{{0,20}}?)[：:]\s*"
        rf"(.+?)(?=(?:{name_alt}).{{0,8}}?(?:{DIALOGUE_VERBS}).{{0,20}}?[：:]|\n\n|\Z)",
        re.DOTALL,
    )

    for match in pattern.finditer(text):
        name = match.group(1)
        raw = match.group(5).strip()
        quoted = re.findall(f"[{LQ}「](.+?)[{RQ}」]", raw)
        if quoted:
            for q in quoted:
                sentences = _split_dialogue_sentences(q.strip())
                result.setdefault(name, []).extend(sentences)
        else:
            sentences = _split_dialogue_sentences(raw)
            result.setdefault(name, []).extend(sentences)

    return result


def compute_voice_profile(name: str, lines: list[str]) -> CharacterVoiceProfile:
    if not lines:
        return CharacterVoiceProfile(character_name=name)

    cleaned = [_clean_line(l) for l in lines]
    cleaned = [l for l in cleaned if l]

    lengths = [len(l) for l in cleaned]
    avg_len = sum(lengths) / len(lengths) if lengths else 0.0

    all_chars = "".join(cleaned)
    words = _tokenize_words(all_chars)
    word_counts = Counter(words)
    top_10 = [w for w, _ in word_counts.most_common(10)]

    total_chars = len(all_chars)
    particle_freq: dict[str, float] = {}
    for p in PARTICLES:
        count = all_chars.count(p)
        if count > 0:
            particle_freq[p] = round(count / total_chars, 4) if total_chars else 0.0

    rhetorical_count = sum(1 for l in cleaned if l.endswith("？") or l.endswith("?"))
    rhetorical_ratio = round(rhetorical_count / len(cleaned), 4) if cleaned else 0.0

    return CharacterVoiceProfile(
        character_name=name,
        dialogue_count=len(cleaned),
        avg_sentence_length=round(avg_len, 1),
        top_10_words=top_10,
        particle_frequency=particle_freq,
        rhetorical_question_ratio=rhetorical_ratio,
        sample_lines=cleaned[:3],
    )


def compute_similarity(a: CharacterVoiceProfile, b: CharacterVoiceProfile) -> float:
    if not a.top_10_words or not b.top_10_words:
        return 0.0

    all_words = set(a.top_10_words + b.top_10_words)
    vec_a = _word_vector(a.top_10_words, all_words)
    vec_b = _word_vector(b.top_10_words, all_words)
    cosine = _cosine(vec_a, vec_b) if all_words else 0.0

    max_len = max(a.avg_sentence_length, b.avg_sentence_length, 1)
    len_diff = abs(a.avg_sentence_length - b.avg_sentence_length) / max_len
    len_score = 1.0 - len_diff

    all_particles = set(a.particle_frequency.keys()) | set(b.particle_frequency.keys())
    if all_particles:
        particle_diff = sum(
            abs(a.particle_frequency.get(p, 0) - b.particle_frequency.get(p, 0))
            for p in all_particles
        ) / len(all_particles)
        particle_score = 1.0 - min(particle_diff, 1.0)
    else:
        particle_score = 1.0

    return round(0.5 * cosine + 0.3 * len_score + 0.2 * particle_score, 4)


def analyze_character_voices(
    project_dir: Path,
    chapter_num: int,
    chapter_text: str | None = None,
) -> VoiceFingerprint:
    project_dir = Path(project_dir)
    if chapter_text is None:
        ch = f"{chapter_num:03d}"
        draft_path = project_dir / "02_正文" / f"第{ch}章_草稿.md"
        if draft_path.is_file():
            chapter_text = draft_path.read_text(encoding="utf-8")
        else:
            chapter_text = ""
        if not chapter_text.strip():
            return VoiceFingerprint(chapter_number=chapter_num, is_mock=True)

    known_names = _load_character_names(project_dir, chapter_text)
    by_char = extract_dialogue_by_character(chapter_text, known_names)

    profiles = [compute_voice_profile(name, lines) for name, lines in by_char.items()]

    flagged: list[dict] = []
    for i in range(len(profiles)):
        for j in range(i + 1, len(profiles)):
            sim = compute_similarity(profiles[i], profiles[j])
            if sim > 0.7:
                flagged.append({
                    "a": profiles[i].character_name,
                    "b": profiles[j].character_name,
                    "similarity": sim,
                })

    return VoiceFingerprint(
        chapter_number=chapter_num,
        profiles=profiles,
        flagged_pairs=flagged,
    )


def voice_fingerprint_to_prose_hints(fp: VoiceFingerprint) -> str:
    if not fp.profiles:
        return ""

    lines = ["## 角色声音区分提示", ""]
    for p in fp.profiles:
        if p.top_10_words:
            words = "、".join(p.top_10_words[:5])
            lines.append(f"- {p.character_name}：高频词 [{words}]；平均句长 {p.avg_sentence_length} 字")
    if fp.flagged_pairs:
        lines.append("")
        lines.append("### 警告：相似声音")
        for pair in fp.flagged_pairs:
            lines.append(
                f"- {pair['a']} 与 {pair['b']} 声音相似度 {pair['similarity']:.0%}，"
                f"请区分两人的词汇选择、句长或语气词使用。"
            )
    return "\n".join(lines).strip()


def voice_fingerprint_to_revision_hints(fp: VoiceFingerprint) -> str:
    if not fp.flagged_pairs:
        return ""
    lines = ["## 角色声音区分", ""]
    for pair in fp.flagged_pairs:
        a_name, b_name = pair["a"], pair["b"]
        a_profile = next((p for p in fp.profiles if p.character_name == a_name), None)
        b_profile = next((p for p in fp.profiles if p.character_name == b_name), None)
        lines.append(
            f"- {a_name} 与 {b_name} 对白过于相似（{pair['similarity']:.0%}）。"
        )
        if a_profile and a_profile.top_10_words:
            lines.append(f"  {a_name} 高频词：{'、'.join(a_profile.top_10_words[:5])}")
        if b_profile and b_profile.top_10_words:
            lines.append(f"  {b_name} 高频词：{'、'.join(b_profile.top_10_words[:5])}")
        lines.append("  建议：给两人不同的口头禅、句长偏好或语气词习惯。")
    return "\n".join(lines).strip()


def write_voice_diagnostics(
    project_dir: Path, fp: VoiceFingerprint
) -> tuple[Path, Path]:
    project_dir = Path(project_dir)
    ch = f"{fp.chapter_number:03d}"
    log_dir = project_dir / "04_审核日志"
    json_path = log_dir / f"第{ch}章_声音诊断.json"
    md_path = log_dir / f"第{ch}章_声音诊断.md"
    log_dir.mkdir(parents=True, exist_ok=True)
    json_path.write_text(model_to_json(fp) + "\n", encoding="utf-8")
    md_path.write_text(_render_voice_markdown(fp), encoding="utf-8")
    return md_path, json_path


# ── private ──────────────────────────────────────────────────────────────────


def _load_character_names(project_dir: Path, chapter_text: str) -> list[str]:
    char_dir = project_dir / "00_世界观" / "角色档案"
    names: list[str] = []
    if char_dir.exists():
        for path in sorted(char_dir.glob("*.md")):
            stem = path.stem
            if stem == "角色模板":
                continue
            if stem in chapter_text:
                names.append(stem)
    if not names:
        names = _detect_names_from_text(chapter_text)
    return names


def _detect_names_from_text(text: str) -> list[str]:
    pattern = re.compile(r"([一-鿿]{2,4})(?:.{0,6}?)(?:道|说|问|喊|叫|嚷|吼|答|回|应|叹|笑|哭)")
    matches = pattern.findall(text)
    seen: set[str] = set()
    result: list[str] = []
    for m in matches:
        if m not in seen:
            seen.add(m)
            result.append(m)
    return result[:20]


def _split_dialogue_sentences(raw: str) -> list[str]:
    parts = SENTENCE_END.split(raw)
    result: list[str] = []
    for p in parts:
        p = p.strip()
        if p and len(p) >= 2:
            result.append(p)
    return result


def _clean_line(line: str) -> str:
    return PUNCT_CLEAN.sub("", line).strip()


def _tokenize_words(text: str) -> list[str]:
    return [text[i:i + 2] for i in range(len(text) - 1)]


def _word_vector(words: list[str], vocab: set[str]) -> list[float]:
    counts = Counter(words)
    total = max(sum(counts.values()), 1)
    return [counts.get(w, 0) / total for w in vocab]


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sqrt(sum(x * x for x in a))
    norm_b = sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _render_voice_markdown(fp: VoiceFingerprint) -> str:
    lines = [
        f"# 第{fp.chapter_number:03d}章 角色声音诊断",
        "",
        f"- Mock：{'是' if fp.is_mock else '否'}",
        "",
    ]
    if fp.profiles:
        lines.append("## 角色声音指纹")
        lines.append("")
        for p in fp.profiles:
            lines.append(f"### {p.character_name}")
            lines.append(f"- 对白句数：{p.dialogue_count}")
            lines.append(f"- 平均句长：{p.avg_sentence_length} 字")
            if p.top_10_words:
                lines.append(f"- 高频词：{'、'.join(p.top_10_words[:5])}")
            if p.particle_frequency:
                particles = ", ".join(
                    f"{k}:{v:.2%}" for k, v in sorted(p.particle_frequency.items(), key=lambda x: -x[1])[:5]
                )
                lines.append(f"- 语气词频率：{particles}")
            lines.append(f"- 反问比例：{p.rhetorical_question_ratio:.1%}")
            if p.sample_lines:
                lines.append(f"- 例句：{'；'.join(p.sample_lines[:2])}")
            lines.append("")
    if fp.flagged_pairs:
        lines.append("## 声音相似警告")
        for pair in fp.flagged_pairs:
            lines.append(f"- {pair['a']} ↔ {pair['b']}：相似度 {pair['similarity']:.0%}")
    return "\n".join(lines).strip() + "\n"
