import json
import tempfile
import unittest
from pathlib import Path

import novel_pipeline
from pydantic import ValidationError

from dramatic_arc_diagnostics import (
    _mock_diagnostics,
    _parse_response,
    diagnose_chapter_drama,
    diagnostics_to_revision_brief,
    write_diagnostics,
)
from novel_schemas import DramaticDiagnostics, SceneTension


def _diag_payload(chapter_number: int = 1) -> dict:
    return {
        "chapter_number": chapter_number,
        "title": "雨夜",
        "model_used": "unit-model",
        "provider_used": "unit",
        "pressure_curve_score": 60,
        "character_arc_score": 70,
        "cinematic_score": 80,
        "overall_drama_score": 0,
        "scenes": [
            {
                "scene_index": 1,
                "scene_summary": "郁时谌收到警告",
                "must_do": "决定是否隐瞒",
                "cost_if_fail": "秘密暴露",
                "pressure_level": 6,
                "pressure_clarity": 7,
            }
        ],
        "characters": [
            {
                "name": "郁时谌",
                "flaw_or_desire": "想控制局面",
                "engaged": True,
                "evidence_quote": "郁时谌把信压在掌心下面。",
                "arc_movement": "前进",
            }
        ],
        "cinematic_samples": [
            {
                "paragraph_index": 1,
                "excerpt": "雨打在窗上，信纸贴着他的掌心。",
                "visual_score": 8,
                "auditory_score": 7,
                "body_action_score": 7,
                "abstract_word_ratio": 1,
                "rewrite_hint": "保留动作，补明确代价。",
            }
        ],
        "top_revision_targets": ["场景1：代价还可更具体，补一句拒绝后的损失。"],
        "is_mock": False,
    }


class DramaticSchemaTests(unittest.TestCase):
    def test_score_ranges_are_enforced(self) -> None:
        with self.assertRaises(ValidationError):
            DramaticDiagnostics(
                chapter_number=1,
                pressure_curve_score=101,
                character_arc_score=50,
                cinematic_score=50,
                overall_drama_score=50,
            )

        with self.assertRaises(ValidationError):
            SceneTension(scene_index=1, pressure_level=11, pressure_clarity=5)

    def test_overall_score_is_normalized_by_formula(self) -> None:
        diag = _parse_response(json.dumps(_diag_payload(), ensure_ascii=False), 1)

        self.assertEqual(diag.overall_drama_score, 69)


class DramaticParserTests(unittest.TestCase):
    def test_parse_clean_json(self) -> None:
        diag = _parse_response(json.dumps(_diag_payload(2), ensure_ascii=False), 2)

        self.assertEqual(diag.chapter_number, 2)
        self.assertEqual(diag.scenes[0].pressure_level, 6)
        self.assertFalse(diag.is_mock)

    def test_parse_markdown_json_block(self) -> None:
        raw = "```json\n" + json.dumps(_diag_payload(), ensure_ascii=False) + "\n```"

        diag = _parse_response(raw, 1)

        self.assertEqual(diag.characters[0].name, "郁时谌")

    def test_parse_leading_text_json(self) -> None:
        raw = "好的，以下是诊断：\n" + json.dumps(_diag_payload(), ensure_ascii=False)

        diag = _parse_response(raw, 1)

        self.assertEqual(diag.cinematic_score, 80)

    def test_invalid_json_falls_back_and_logs_raw(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            diag = _parse_response("不是 JSON", 1, project_dir=root, fallback_text="郁时谌必须做选择。")

            self.assertTrue(diag.is_mock)
            logs = list((root / "logs" / "dramatic_diagnose_failures").glob("第001章_*.txt"))
            self.assertEqual(len(logs), 1)
            self.assertIn("不是 JSON", logs[0].read_text(encoding="utf-8"))


class DramaticMockTests(unittest.TestCase):
    def test_mock_returns_valid_diagnostics(self) -> None:
        text = "# 第001章：雨夜\n\n郁时谌把信压在掌心下面。“你必须今晚决定。”沈逐光说。雨声敲着窗。"

        diag = _mock_diagnostics(1, text)

        self.assertTrue(diag.is_mock)
        self.assertGreaterEqual(diag.overall_drama_score, 0)
        self.assertTrue(diag.scenes)
        self.assertTrue(diag.cinematic_samples)

    def test_mock_scores_are_stable_for_same_input(self) -> None:
        text = "郁时谌必须选择是否公开秘密。他推开门，雨声从走廊灌进来。"

        a = _mock_diagnostics(1, text)
        b = _mock_diagnostics(1, text)

        self.assertEqual(a.overall_drama_score, b.overall_drama_score)
        self.assertEqual(a.top_revision_targets, b.top_revision_targets)


class DramaticPersistenceTests(unittest.TestCase):
    def test_write_creates_json_md_and_versions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            diag = _mock_diagnostics(1, "郁时谌必须选择。他把信放进抽屉。")

            md_path, json_path = write_diagnostics(root, diag)
            self.assertTrue(md_path.exists())
            self.assertTrue(json_path.exists())
            self.assertIn("戏剧诊断", md_path.read_text(encoding="utf-8"))

            write_diagnostics(root, diag)
            backups = list((root / "04_审核日志" / "versions").glob("第001章_戏剧诊断_*.json"))
            self.assertEqual(len(backups), 1)

    def test_revision_brief_includes_targets(self) -> None:
        diag = _mock_diagnostics(1, "郁时谌必须选择。他推开门，雨声很响。")
        brief = diagnostics_to_revision_brief(diag)

        self.assertIn("戏剧诊断改稿任务", brief)
        self.assertIn("压力曲线", brief)
        self.assertIn("1.", brief)

    def test_empty_revision_targets_returns_empty(self) -> None:
        diag = _mock_diagnostics(1, "郁时谌必须选择。他推开门，雨声很响。")
        diag.top_revision_targets = []

        self.assertEqual(diagnostics_to_revision_brief(diag), "")


class DramaticRoutingTests(unittest.TestCase):
    def test_mock_mode_does_not_call_critic_provider(self) -> None:
        class MockRouter:
            mode = "mock"
            CRITIC_PROVIDER = "deepseek"

            def critic_text(self, *args, **kwargs):  # pragma: no cover - must not be called
                raise AssertionError("critic_text should not be called in mock mode")

        with tempfile.TemporaryDirectory() as tmp:
            diag = diagnose_chapter_drama(Path(tmp), 1, "郁时谌必须选择。", llm=MockRouter())

        self.assertTrue(diag.is_mock)

    def test_real_mode_uses_critic_text_with_dramatic_labels(self) -> None:
        class CaptureRouter:
            mode = "real"
            CRITIC_PROVIDER = "deepseek"
            DEEPSEEK_MODEL = "deepseek-unit"

            def __init__(self) -> None:
                self.kwargs = {}

            def critic_text(self, **kwargs):
                self.kwargs = kwargs
                return json.dumps(_diag_payload(), ensure_ascii=False)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "prompts").mkdir(parents=True)
            (root / "prompts" / "戏剧诊断.md").write_text(
                "{{ axis_context }}\n{{ json_schema }}",
                encoding="utf-8",
            )
            router = CaptureRouter()
            diag = diagnose_chapter_drama(root, 1, "郁时谌必须选择。", llm=router)

        self.assertFalse(diag.is_mock)
        self.assertEqual(router.kwargs["workflow"], "dramatic-diagnose")
        self.assertEqual(router.kwargs["role"], "dramatic-critic")
        self.assertIn("本章正文", router.kwargs["user_prompt"])


class DramaticCLITests(unittest.TestCase):
    def test_pipeline_standalone_dramatic_diagnose_writes_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "02_正文").mkdir(parents=True)
            (root / "04_审核日志").mkdir(parents=True)
            (root / "01_大纲" / "章纲").mkdir(parents=True)
            (root / "02_正文" / "第001章_草稿.md").write_text(
                "# 第001章：雨夜\n\n郁时谌必须选择是否公开秘密。他推开门，雨声从走廊灌进来。",
                encoding="utf-8",
            )
            old_project_dir = novel_pipeline.PROJECT_DIR
            novel_pipeline.PROJECT_DIR = root
            try:
                novel_pipeline.run_dramatic_diagnose(1, mock=True)
            finally:
                novel_pipeline.PROJECT_DIR = old_project_dir

            self.assertTrue((root / "04_审核日志" / "第001章_戏剧诊断.md").exists())
            self.assertTrue((root / "04_审核日志" / "第001章_戏剧诊断.json").exists())


if __name__ == "__main__":
    unittest.main()
