import json
import tempfile
import unittest
from pathlib import Path

from novel_schemas import CharacterVoiceProfile, VoiceFingerprint
from voice_diagnostics import (
    _detect_names_from_text,
    _split_dialogue_sentences,
    _clean_line,
    _tokenize_words,
    analyze_character_voices,
    compute_similarity,
    compute_voice_profile,
    extract_dialogue_by_character,
    voice_fingerprint_to_prose_hints,
    voice_fingerprint_to_revision_hints,
    write_voice_diagnostics,
)


# ── Test fixtures ────────────────────────────────────────────────────────────

MULTI_CHAR_TEXT = """

郁时谌把信压在掌心下面。沈逐光站在门口，雨声从走廊灌进来。

沈逐光说："你以为我不知道你在想什么？"她顿了顿，声音变低："但这件事不是你想的那样。"

郁时谌叹了一声："那我该怎么做？等死吗？"

沈逐光道："你从来都是这样——只相信自己，不相信别人。"她转过身去，"温漪呢？你也不信她？"
"""

SAME_VOICE_TEXT = """

郁时谌道："我觉得今天天气不错，你觉得呢？"
沈逐光说："我也觉得今天天气不错，确实挺好的。"
郁时谌道："那我们去散步吧，怎么样呢？"
沈逐光说："好的呢，去散步吧。"
"""

NO_DIALOGUE_TEXT = "雨打在窗上。走廊里空无一人。桌上的信纸微微发潮。时钟敲了三下。"


# ── Schema tests ─────────────────────────────────────────────────────────────


class VoiceSchemaTests(unittest.TestCase):
    def test_profile_defaults(self) -> None:
        p = CharacterVoiceProfile(character_name="郁时谌")
        self.assertEqual(p.character_name, "郁时谌")
        self.assertEqual(p.dialogue_count, 0)
        self.assertEqual(p.top_10_words, [])
        self.assertEqual(p.particle_frequency, {})

    def test_fingerprint_defaults(self) -> None:
        fp = VoiceFingerprint(chapter_number=1)
        self.assertEqual(fp.chapter_number, 1)
        self.assertEqual(fp.profiles, [])
        self.assertEqual(fp.flagged_pairs, [])
        self.assertFalse(fp.is_mock)

    def test_fingerprint_json_roundtrip(self) -> None:
        fp = VoiceFingerprint(
            chapter_number=2,
            profiles=[
                CharacterVoiceProfile(
                    character_name="郁时谌",
                    dialogue_count=5,
                    avg_sentence_length=12.3,
                    top_10_words=["知道", "必须", "选择"],
                    particle_frequency={"呢": 0.03, "吧": 0.01},
                    rhetorical_question_ratio=0.2,
                    sample_lines=["你必须今晚决定。"],
                ),
            ],
            flagged_pairs=[{"a": "郁时谌", "b": "沈逐光", "similarity": 0.82}],
        )
        raw = fp.model_dump_json(indent=2)
        restored = VoiceFingerprint.model_validate(json.loads(raw))

        self.assertEqual(restored.profiles[0].character_name, "郁时谌")
        self.assertEqual(restored.flagged_pairs[0]["similarity"], 0.82)


# ── Dialogue extraction tests ────────────────────────────────────────────────


class DialogueExtractionTests(unittest.TestCase):
    def test_extract_multi_character(self) -> None:
        by_char = extract_dialogue_by_character(
            MULTI_CHAR_TEXT, known_names=["郁时谌", "沈逐光"]
        )
        self.assertIn("郁时谌", by_char)
        self.assertIn("沈逐光", by_char)
        self.assertGreaterEqual(len(by_char["郁时谌"]), 1)

    def test_extract_no_dialogue(self) -> None:
        by_char = extract_dialogue_by_character(
            NO_DIALOGUE_TEXT, known_names=["郁时谌"]
        )
        self.assertEqual(by_char, {})

    def test_extract_auto_detects_names(self) -> None:
        by_char = extract_dialogue_by_character(MULTI_CHAR_TEXT)
        self.assertGreater(len(by_char), 0)

    def test_detect_names_basic(self) -> None:
        names = _detect_names_from_text(MULTI_CHAR_TEXT)
        self.assertIn("郁时谌", names)
        self.assertIn("沈逐光", names)


# ── Voice profile tests ──────────────────────────────────────────────────────


class VoiceProfileTests(unittest.TestCase):
    def test_empty_lines(self) -> None:
        p = compute_voice_profile("测试", [])
        self.assertEqual(p.dialogue_count, 0)
        self.assertEqual(p.avg_sentence_length, 0.0)

    def test_profile_stats(self) -> None:
        lines = ["你必须今晚决定。", "我没有时间再等了。"]
        p = compute_voice_profile("郁时谌", lines)

        self.assertEqual(p.dialogue_count, 2)
        self.assertGreater(p.avg_sentence_length, 0)
        self.assertGreaterEqual(len(p.top_10_words), 1)

    def test_rhetorical_question_detection(self) -> None:
        p = compute_voice_profile("测试", ["你以为我不知道？", "难道不是吗？", "走吧。"])
        self.assertGreater(p.rhetorical_question_ratio, 0.5)

    def test_particle_frequency(self) -> None:
        p = compute_voice_profile("测试", ["好呢好呢。", "是吧是吧。"])
        self.assertIn("呢", p.particle_frequency)
        self.assertIn("吧", p.particle_frequency)


# ── Similarity tests ─────────────────────────────────────────────────────────


class SimilarityTests(unittest.TestCase):
    def test_identical_voices(self) -> None:
        a = CharacterVoiceProfile(
            character_name="A",
            dialogue_count=5,
            avg_sentence_length=10.0,
            top_10_words=["知道", "必须", "应该", "可能", "觉得"],
            particle_frequency={"呢": 0.05, "吧": 0.03},
            rhetorical_question_ratio=0.2,
        )
        b = CharacterVoiceProfile(
            character_name="B",
            dialogue_count=5,
            avg_sentence_length=10.0,
            top_10_words=["知道", "必须", "应该", "可能", "觉得"],
            particle_frequency={"呢": 0.05, "吧": 0.03},
            rhetorical_question_ratio=0.2,
        )
        sim = compute_similarity(a, b)
        self.assertGreater(sim, 0.85)

    def test_different_voices(self) -> None:
        a = CharacterVoiceProfile(
            character_name="A",
            top_10_words=["知道", "必须", "选择", "时间", "公开"],
            avg_sentence_length=8.0,
            particle_frequency={"呢": 0.02},
        )
        b = CharacterVoiceProfile(
            character_name="B",
            top_10_words=["温柔", "想起", "过去", "阳光", "微笑"],
            avg_sentence_length=15.0,
            particle_frequency={"啊": 0.06},
        )
        sim = compute_similarity(a, b)
        self.assertLess(sim, 0.5)

    def test_empty_profiles(self) -> None:
        a = CharacterVoiceProfile(character_name="A")
        b = CharacterVoiceProfile(character_name="B")
        self.assertEqual(compute_similarity(a, b), 0.0)


# ── Full analysis tests ──────────────────────────────────────────────────────


class FullAnalysisTests(unittest.TestCase):
    def test_analyze_multi_char(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            char_dir = root / "00_世界观" / "角色档案"
            char_dir.mkdir(parents=True)
            (char_dir / "郁时谌.md").write_text("# 郁时谌\n主角", encoding="utf-8")
            (char_dir / "沈逐光.md").write_text("# 沈逐光\n配角", encoding="utf-8")
            (char_dir / "角色模板.md").write_text("# 模板", encoding="utf-8")

            fp = analyze_character_voices(root, 1, MULTI_CHAR_TEXT)

            self.assertEqual(fp.chapter_number, 1)
            self.assertGreaterEqual(len(fp.profiles), 1)

    def test_analyze_same_voice_flags(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            char_dir = root / "00_世界观" / "角色档案"
            char_dir.mkdir(parents=True)
            (char_dir / "郁时谌.md").write_text("# 郁时谌", encoding="utf-8")
            (char_dir / "沈逐光.md").write_text("# 沈逐光", encoding="utf-8")

            fp = analyze_character_voices(root, 1, SAME_VOICE_TEXT)

            self.assertGreaterEqual(len(fp.profiles), 1)

    def test_analyze_no_dialogue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            fp = analyze_character_voices(root, 1, NO_DIALOGUE_TEXT)

            self.assertEqual(fp.profiles, [])
            self.assertEqual(fp.flagged_pairs, [])

    def test_analyze_from_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "02_正文").mkdir(parents=True)
            (root / "02_正文" / "第001章_草稿.md").write_text(
                MULTI_CHAR_TEXT, encoding="utf-8"
            )

            fp = analyze_character_voices(root, 1)

            self.assertEqual(fp.chapter_number, 1)

    def test_analyze_missing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fp = analyze_character_voices(root, 1)
            self.assertTrue(fp.is_mock)


# ── Hint generation tests ────────────────────────────────────────────────────


class HintGenerationTests(unittest.TestCase):
    def test_prose_hints_empty(self) -> None:
        fp = VoiceFingerprint(chapter_number=1)
        self.assertEqual(voice_fingerprint_to_prose_hints(fp), "")

    def test_prose_hints_with_profiles(self) -> None:
        fp = VoiceFingerprint(
            chapter_number=1,
            profiles=[
                CharacterVoiceProfile(
                    character_name="郁时谌",
                    top_10_words=["知道", "必须", "选择"],
                    avg_sentence_length=12.0,
                ),
            ],
        )
        hints = voice_fingerprint_to_prose_hints(fp)
        self.assertIn("角色声音区分", hints)
        self.assertIn("郁时谌", hints)

    def test_prose_hints_with_flags(self) -> None:
        fp = VoiceFingerprint(
            chapter_number=1,
            profiles=[
                CharacterVoiceProfile(
                    character_name="郁时谌",
                    top_10_words=["知道", "必须"],
                    avg_sentence_length=10.0,
                ),
                CharacterVoiceProfile(
                    character_name="沈逐光",
                    top_10_words=["知道", "必须"],
                    avg_sentence_length=10.0,
                ),
            ],
            flagged_pairs=[{"a": "郁时谌", "b": "沈逐光", "similarity": 0.85}],
        )
        hints = voice_fingerprint_to_prose_hints(fp)
        self.assertIn("警告", hints)
        self.assertIn("85%", hints)

    def test_revision_hints_empty(self) -> None:
        fp = VoiceFingerprint(chapter_number=1)
        self.assertEqual(voice_fingerprint_to_revision_hints(fp), "")

    def test_revision_hints_with_flags(self) -> None:
        fp = VoiceFingerprint(
            chapter_number=1,
            profiles=[
                CharacterVoiceProfile(
                    character_name="郁时谌",
                    top_10_words=["知道", "必须"],
                ),
                CharacterVoiceProfile(
                    character_name="沈逐光",
                    top_10_words=["温柔", "想起"],
                ),
            ],
            flagged_pairs=[{"a": "郁时谌", "b": "沈逐光", "similarity": 0.82}],
        )
        hints = voice_fingerprint_to_revision_hints(fp)
        self.assertIn("82%", hints)
        self.assertIn("口头禅", hints)


# ── Persistence tests ────────────────────────────────────────────────────────


class VoicePersistenceTests(unittest.TestCase):
    def test_write_creates_json_and_md(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fp = VoiceFingerprint(
                chapter_number=1,
                profiles=[
                    CharacterVoiceProfile(
                        character_name="测试",
                        dialogue_count=3,
                        avg_sentence_length=10.0,
                    ),
                ],
                flagged_pairs=[{"a": "A", "b": "B", "similarity": 0.75}],
            )

            md_path, json_path = write_voice_diagnostics(root, fp)

            self.assertTrue(md_path.exists())
            self.assertTrue(json_path.exists())
            self.assertIn("声音诊断", md_path.read_text(encoding="utf-8"))

    def test_write_markdown_includes_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fp = VoiceFingerprint(
                chapter_number=3,
                flagged_pairs=[{"a": "X", "b": "Y", "similarity": 0.88}],
            )

            md_path, _ = write_voice_diagnostics(root, fp)
            content = md_path.read_text(encoding="utf-8")

            self.assertIn("声音相似警告", content)
            self.assertIn("88%", content)


# ── Helper tests ─────────────────────────────────────────────────────────────


class HelperTests(unittest.TestCase):
    def test_split_dialogue_sentences(self) -> None:
        parts = _split_dialogue_sentences("走吧。去哪？不知道。")
        self.assertGreaterEqual(len(parts), 2)

    def test_clean_line_removes_brackets(self) -> None:
        self.assertEqual(_clean_line("「你好」"), "你好")

    def test_tokenize_words(self) -> None:
        tokens = _tokenize_words("你必须今晚决定")
        self.assertIn("必须", tokens)
        self.assertIn("今晚", tokens)


if __name__ == "__main__":
    unittest.main()
