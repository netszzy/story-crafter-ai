"""
V4.0 Phase C -- ji qiao qu dong sheng cheng + zheng wen bian ji qu ce shi。

Ce shi: ChapterTaskCard technique_focus xu lie hua wang fan, ji qiao zhi ling zhu ru,
chang jing lei xing tui jian, kong lie biao bu zhu ru kong kuai, scene_type_techniques wan bei.
"""

import json
import tempfile
import unittest
from pathlib import Path

from novel_schemas import ChapterTaskCard


class TechniqueFocusSchemaTests(unittest.TestCase):
    """ChapterTaskCard.technique_focus xu lie hua wang fan."""

    def test_serialize_technique_focus_roundtrip(self):
        """technique_focus zai JSON zhong bao chi bu bian."""
        card = ChapterTaskCard(
            chapter_number=1,
            technique_focus=["短句冲击", "感官锚点"],
        )
        data = json.loads(card.model_dump_json())
        self.assertEqual(data["technique_focus"], ["短句冲击", "感官锚点"])
        recon = ChapterTaskCard.model_validate(data)
        self.assertEqual(recon.technique_focus, ["短句冲击", "感官锚点"])

    def test_default_empty_list(self):
        """default wei kong lie biao."""
        card = ChapterTaskCard(chapter_number=2)
        self.assertEqual(card.technique_focus, [])

    def test_technique_focus_preserved_after_field_update(self):
        """xiu gai qi ta zi duan shi technique_focus bu bei dong."""
        card = ChapterTaskCard(
            chapter_number=3,
            technique_focus=["潜台词"],
            title="test",
        )
        card.title = "updated"
        self.assertEqual(card.technique_focus, ["潜台词"])


class SceneTypeTechniquesTests(unittest.TestCase):
    """scene_type_techniques() ge chang jing lei xing tui jian."""

    def setUp(self):
        from prompt_assembly import scene_type_techniques as fn
        self.fn = fn

    def test_opening_scene(self):
        t = self.fn("开场")
        self.assertIn("短句冲击", t)
        self.assertIn("感官锚点", t)

    def test_confrontation_scene(self):
        t = self.fn("对峙")
        self.assertIn("潜台词", t)
        self.assertIn("身体反应替代副词", t)

    def test_emotional_scene(self):
        t = self.fn("情感")
        self.assertIn("身体化情感", t)
        self.assertIn("留白", t)

    def test_action_scene(self):
        t = self.fn("动作")
        self.assertIn("连续动作链", t)
        self.assertIn("短句冲击", t)

    def test_revelation_scene(self):
        t = self.fn("揭示")
        self.assertIn("信息折叠", t)
        self.assertIn("潜台词", t)

    def test_transition_scene(self):
        t = self.fn("过渡")
        self.assertIn("环境拟人", t)
        self.assertIn("感官锚点", t)

    def test_climax_scene(self):
        t = self.fn("高潮")
        self.assertIn("短句冲击", t)
        self.assertIn("连续动作链", t)
        self.assertIn("身体化情感", t)

    def test_epilogue_scene(self):
        t = self.fn("尾声")
        self.assertIn("留白", t)
        self.assertIn("环境拟人", t)

    def test_unknown_scene_type_fallback(self):
        t = self.fn("buzhidao")
        self.assertIsInstance(t, list)
        self.assertTrue(len(t) >= 2)

    def test_all_known_types_return_lists(self):
        for stype in ["开场", "对峙", "情感",
                       "动作", "揭示", "过渡",
                       "高潮", "尾声"]:
            with self.subTest(scene_type=stype):
                result = self.fn(stype)
                self.assertIsInstance(result, list)
                self.assertTrue(len(result) >= 2, f"{stype} should have >=2 techniques")


class TechniqueLibraryTests(unittest.TestCase):
    """_technique_tips_library() wan bei xing."""

    @classmethod
    def setUpClass(cls):
        from prompt_assembly import _technique_tips_library
        cls.lib = _technique_tips_library()

    def test_all_technique_selectors_in_library(self):
        ui_techniques = [
            "短句冲击", "感官锚点", "潜台词",
            "身体反应替代副词", "身体化情感",
            "连续动作链", "留白", "信息折叠",
            "环境拟人",
        ]
        for tech in ui_techniques:
            with self.subTest(technique=tech):
                self.assertIn(tech, self.lib)
                self.assertTrue(len(self.lib[tech]) > 10, f"{tech} tip too short")

    def test_library_size(self):
        self.assertGreaterEqual(len(self.lib), 9)


class RenderTechniqueEnforcementTests(unittest.TestCase):
    """render_technique_enforcement() shu chu ge shi."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        (self.tmpdir / "01_大纲" / "章纲").mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_card(self, ch_num: int, techniques: list[str]) -> None:
        from novel_schemas import model_to_json
        card = ChapterTaskCard(
            chapter_number=ch_num,
            technique_focus=techniques,
        )
        path = self.tmpdir / "01_大纲" / "章纲" / f"第{ch_num:03d}章_task_card.json"
        path.write_text(model_to_json(card) + "\n", encoding="utf-8")

    def _call(self, ch_num: int) -> str:
        from prompt_assembly import render_technique_enforcement
        return render_technique_enforcement(self.tmpdir, ch_num)

    def test_empty_techniques_returns_empty_string(self):
        self._write_card(1, [])
        result = self._call(1)
        self.assertEqual(result, "")

    def test_single_technique_returns_block(self):
        self._write_card(1, ["留白"])
        result = self._call(1)
        self.assertIn("本章必须使用的写作技巧", result)
        self.assertIn("留白", result)

    def test_multiple_techniques_all_listed(self):
        self._write_card(2, ["短句冲击", "潜台词", "环境拟人"])
        result = self._call(2)
        self.assertIn("短句冲击", result)
        self.assertIn("潜台词", result)
        self.assertIn("环境拟人", result)

    def test_missing_card_returns_empty(self):
        result = self._call(99)
        self.assertEqual(result, "")

    def test_technique_block_has_markdown_header(self):
        self._write_card(3, ["感官锚点"])
        result = self._call(3)
        self.assertTrue(result.startswith("##"), f"Should start with ##: {result[:20]}")


class ProsePromptInjectionTests(unittest.TestCase):
    """yan zheng ji qiao zhi ling zhu ru dao prose sheng cheng prompt zhong."""

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        (self.tmpdir / "01_大纲" / "章纲").mkdir(parents=True, exist_ok=True)
        (self.tmpdir / "00_世界观").mkdir(parents=True, exist_ok=True)
        (self.tmpdir / "04_审核日志").mkdir(parents=True, exist_ok=True)
        (self.tmpdir / "prompts").mkdir(parents=True, exist_ok=True)
        spec = json.dumps({"genre": "悬疑", "core_conflict": "冲突测试"}, ensure_ascii=False)
        (self.tmpdir / "00_世界观" / "故事规格.md").write_text(spec, encoding="utf-8")
        (self.tmpdir / "prompts" / "正文生成prologue.md").write_text(
            "{genre_hint}\n{audience_hint}\n{core_conflict}\n{selling_points}\n"
            "{style_rules}\n{style_samples}\n{constitution}\n",
            encoding="utf-8",
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_card(self, ch_num: int, techniques: list[str]) -> None:
        from novel_schemas import model_to_json
        card = ChapterTaskCard(
            chapter_number=ch_num,
            technique_focus=techniques,
        )
        path = self.tmpdir / "01_大纲" / "章纲" / f"第{ch_num:03d}章_task_card.json"
        path.write_text(model_to_json(card) + "\n", encoding="utf-8")

    def _call(self, ch_num: int) -> str:
        from prompt_assembly import render_prose_system_prompt
        return render_prose_system_prompt(self.tmpdir, ch_num)

    def test_prompt_includes_technique_block_when_present(self):
        self._write_card(1, ["身体化情感"])
        result = self._call(1)
        self.assertIn("本章必须使用的写作技巧", result)

    def test_prompt_excludes_technique_block_when_empty(self):
        self._write_card(1, [])
        result = self._call(1)
        self.assertNotIn("本章必须使用的写作技巧", result)

    def test_prompt_includes_all_selected_techniques(self):
        self._write_card(2, ["短句冲击", "留白", "信息折叠"])
        result = self._call(2)
        self.assertIn("短句冲击", result)
        self.assertIn("留白", result)
        self.assertIn("信息折叠", result)

    def test_prompt_without_card_still_ok(self):
        result = self._call(1)
        self.assertIsInstance(result, str)
        self.assertTrue(len(result) > 0)
        self.assertNotIn("本章必须使用的写作技巧", result)


if __name__ == "__main__":
    unittest.main()
