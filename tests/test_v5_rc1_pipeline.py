"""V5.0-rc1 管线层专项测试：质量诊断、文学批评、风格法庭、编辑备忘录"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


class QualityDiagnosticsPipelineTests(unittest.TestCase):
    """质量诊断管线测试"""

    def setUp(self):
        from quality_diagnostics import write_writer_override, read_writer_overrides, apply_writer_overrides
        self.write_writer_override = write_writer_override
        self.read_writer_overrides = read_writer_overrides
        self.apply_writer_overrides = apply_writer_overrides
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "04_审核日志").mkdir(parents=True, exist_ok=True)

    def test_full_cycle_write_read_apply(self):
        """完整裁决周期：写入 → 读取 → 应用到诊断报告 → 验证"""
        from quality_diagnostics import _active_findings

        self.write_writer_override(self.tmp, 1,
            rejected_advice="冲突信号偏弱", writer_reason="氛围章不适用冲突标准",
            action="protect", finding_key="conflict_weak")

        overrides = self.read_writer_overrides(self.tmp, 1)
        self.assertEqual(len(overrides), 1)

        report = {
            "findings": [
                {"level": "warning", "item": "冲突信号偏弱", "detail": "本章冲突不足"},
                {"level": "warning", "item": "对白比例偏高", "detail": ""},
            ],
            "score": 70,
        }
        result = self.apply_writer_overrides(report, overrides)

        findings = result["findings"]
        levels = {f["item"]: f["level"] for f in findings}
        self.assertEqual(levels["冲突信号偏弱"], "accepted_by_writer")
        self.assertEqual(levels["对白比例偏高"], "warning")

        active = _active_findings(findings)
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["item"], "对白比例偏高")

        # FINDING_SCORE_PENALTIES["冲突信号偏弱"] = 10 → score = 70+10 = 80
        self.assertEqual(result["score"], 80)

    def test_rebut_preserves_writer_action_field(self):
        self.write_writer_override(self.tmp, 2,
            rejected_advice="角色主动性偏弱", writer_reason="人物此刻被动是性格",
            action="rebut", finding_key="agency_weak")

        overrides = self.read_writer_overrides(self.tmp, 2)
        report = {"findings": [{"level": "warning", "item": "角色主动性偏弱"}], "score": 75}
        result = self.apply_writer_overrides(report, overrides)
        finding = result["findings"][0]
        self.assertEqual(finding["level"], "rebutted_by_writer")
        self.assertEqual(finding["writer_action"], "rebut")
        self.assertEqual(finding["writer_reason"], "人物此刻被动是性格")

    def test_adopt_does_not_refund_score(self):
        self.write_writer_override(self.tmp, 3,
            rejected_advice="对白比例偏高", writer_reason="同意修改",
            action="adopt")

        overrides = self.read_writer_overrides(self.tmp, 3)
        report = {"findings": [{"level": "warning", "item": "对白比例偏高"}], "score": 70}
        result = self.apply_writer_overrides(report, overrides)
        finding = result["findings"][0]
        self.assertEqual(finding["level"], "warning")
        self.assertEqual(finding["writer_action"], "adopt")
        self.assertEqual(result["score"], 70)

    def test_multiple_overrides_on_same_finding_last_wins(self):
        self.write_writer_override(self.tmp, 4,
            rejected_advice="可感细节偏少", writer_reason="先保护", action="protect")
        self.write_writer_override(self.tmp, 4,
            rejected_advice="可感细节偏少", writer_reason="改主意采纳", action="adopt")

        overrides = self.read_writer_overrides(self.tmp, 4)
        report = {"findings": [{"level": "info", "item": "可感细节偏少"}], "score": 80}
        result = self.apply_writer_overrides(report, overrides)
        finding = result["findings"][0]
        self.assertEqual(finding["writer_action"], "adopt")

    def test_override_not_matching_any_finding(self):
        self.write_writer_override(self.tmp, 5,
            rejected_advice="不存在的诊断项", writer_reason="测试", action="protect")

        overrides = self.read_writer_overrides(self.tmp, 5)
        report = {"findings": [{"level": "warning", "item": "可感细节偏少"}], "score": 80}
        result = self.apply_writer_overrides(report, overrides)
        self.assertEqual(result["score"], 80)
        self.assertEqual(result["findings"][0]["level"], "warning")


class StyleCourtPipelineTests(unittest.TestCase):
    """风格法庭管线测试"""

    def setUp(self):
        from novel_schemas import LiteraryView, MemorableMoment
        self.LiteraryView = LiteraryView
        self.MemorableMoment = MemorableMoment
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "04_审核日志").mkdir(parents=True, exist_ok=True)
        (self.tmp / "01_大纲" / "章纲").mkdir(parents=True, exist_ok=True)

    def _make_lit_view(self, **kw):
        defaults = dict(
            chapter_number=1, cannot_be_quantified=True, is_mock=True,
            memorable_moments=[], unsaid_tension=[], reader_residue=[],
            moral_ambiguity=[], self_deception_signals=[], literary_risks=[],
        )
        defaults.update(kw)
        return self.LiteraryView(**defaults)

    def test_hard_issue_detection(self):
        from style_court import _is_hard_issue

        self.assertTrue(_is_hard_issue({"level": "error", "item": "逻辑矛盾", "detail": ""}))
        # warning + no HARD_TERMS match → not hard
        self.assertFalse(_is_hard_issue({"level": "warning", "item": "冲突信号偏弱", "detail": ""}))

    def test_soft_literary_issue_detection(self):
        from style_court import _is_soft_literary_issue

        self.assertTrue(_is_soft_literary_issue({"item": "冲突信号偏弱"}))
        self.assertTrue(_is_soft_literary_issue({"item": "角色主动性偏弱"}))
        # "对白比例" 在 SOFT_LITERARY_TERMS 中 → "对白比例偏高" 是 soft
        self.assertTrue(_is_soft_literary_issue({"item": "对白比例偏高"}))

    def test_active_findings_excludes_writer_actions(self):
        from style_court import _active_findings

        report = {
            "findings": [
                {"level": "error", "item": "逻辑矛盾"},
                {"level": "accepted_by_writer", "item": "x"},
                {"level": "rebutted_by_writer", "item": "y"},
                {"level": "warning", "item": "z"},
            ]
        }
        active = _active_findings(report)
        self.assertEqual(len(active), 2)

    def test_adjudicate_protected_mode(self):
        from style_court import adjudicate

        quality = {
            "task_card_alignment": {"chapter_mode": "interior", "style_profile": "wang_xiaobo"},
            "findings": [
                {"level": "warning", "item": "冲突信号偏弱", "detail": "冲突不足"},
                {"level": "warning", "item": "可感细节偏少", "detail": ""},
            ]
        }
        lit = self._make_lit_view()
        decision = adjudicate(self.tmp, 1, quality, lit, None)
        # interior + cannot_be_quantified → protected → soft issues → contested
        self.assertEqual(len(decision.contested_issues), 2)
        self.assertEqual(len(decision.confirmed_issues), 0)

    def test_adjudicate_hard_issues_always_confirmed(self):
        from style_court import adjudicate

        quality = {
            "task_card_alignment": {"chapter_mode": "interior", "style_profile": ""},
            "findings": [{"level": "error", "item": "逻辑矛盾", "detail": "时间线断裂"}],
        }
        lit = self._make_lit_view()
        decision = adjudicate(self.tmp, 1, quality, lit, None)
        self.assertEqual(len(decision.confirmed_issues), 1)
        self.assertEqual(len(decision.contested_issues), 0)

    def test_adjudicate_without_literary_view(self):
        """无 LiteraryView 时不应保护任何 finding"""
        from style_court import adjudicate

        quality = {
            "task_card_alignment": {"chapter_mode": "interior", "style_profile": ""},
            "findings": [
                {"level": "warning", "item": "冲突信号偏弱", "detail": "冲突不足"},
            ]
        }
        decision = adjudicate(self.tmp, 1, quality, None, None)
        # 没有 literary_view → not protected → all confirmed
        self.assertEqual(len(decision.confirmed_issues), 1)
        self.assertEqual(len(decision.contested_issues), 0)

    def test_contested_to_reservations(self):
        from style_court import contested_to_reservations
        from novel_schemas import StyleCourtDecision

        decision = StyleCourtDecision(
            chapter_number=1,
            chapter_mode="interior",
            style_profile="wang_xiaobo",
            cannot_be_quantified=True,
            is_mock=True,
            confirmed_issues=[],
            contested_issues=[
                {"source": "quality", "issue": "冲突信号偏弱：冲突不足",
                 "reason": "氛围章不适用冲突标准", "finding_key": "k1"},
            ],
            literary_priorities=[],
        )
        res = contested_to_reservations(decision)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["diagnostic_source"], "quality")
        self.assertEqual(res[0]["rejected_advice"], "冲突信号偏弱：冲突不足")

    def test_write_read_style_court(self):
        from style_court import write_style_court, read_style_court
        from novel_schemas import StyleCourtDecision

        decision = StyleCourtDecision(
            chapter_number=3,
            is_mock=True,
            confirmed_issues=[{"source": "quality", "issue": "逻辑矛盾", "reason": "硬约束"}],
            contested_issues=[],
            literary_priorities=[],
        )
        md_path, json_path = write_style_court(self.tmp, decision)
        self.assertTrue(json_path.exists())
        loaded = read_style_court(self.tmp, 3)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.chapter_number, 3)
        self.assertEqual(len(loaded.confirmed_issues), 1)


class EditorMemoPipelineTests(unittest.TestCase):
    """编辑备忘录管线测试"""

    def test_merge_reservations_excludes_adopt(self):
        from editor_memo import _merge_reservations

        reservations = [
            {"action": "adopt", "diagnostic_source": "quality",
             "rejected_advice": "对白比例偏高", "writer_reason": "同意修改"},
            {"action": "protect", "diagnostic_source": "style_court",
             "rejected_advice": "冲突信号偏弱", "writer_reason": "文学保护"},
            {"action": "rebut", "diagnostic_source": "quality",
             "rejected_advice": "角色主动性偏弱", "writer_reason": "人物性格使然"},
        ]
        merged = _merge_reservations(reservations)
        self.assertEqual(len(merged), 2)
        advices = {m["rejected_advice"] for m in merged}
        self.assertNotIn("对白比例偏高", advices)

    def test_merge_reservations_deduplicate(self):
        from editor_memo import _merge_reservations

        reservations = [
            {"action": "protect", "diagnostic_source": "quality",
             "rejected_advice": "冲突信号偏弱", "writer_reason": "理由1"},
            {"action": "protect", "diagnostic_source": "quality",
             "rejected_advice": "冲突信号偏弱", "writer_reason": "理由2"},
        ]
        merged = _merge_reservations(reservations)
        self.assertEqual(len(merged), 1)

    def test_memo_to_revision_prompt_with_reservations(self):
        """有 must_fix + reservations 时，reservations 出现在 prompt 中"""
        from editor_memo import memo_to_revision_prompt
        from novel_schemas import EditorMemo, DiagnosticReservation, MemoItem

        memo = EditorMemo(
            chapter_number=1,
            overall_assessment="整体尚可",
            ready_for_final=False,
            is_mock=True,
            top_3_must_fix=[
                MemoItem(priority="P0", source="quality",
                         issue="逻辑矛盾", action="修时间线"),
            ],
            contradictions=[],
            reservations=[
                DiagnosticReservation(
                    action="protect", diagnostic_source="quality",
                    rejected_advice="冲突信号偏弱", writer_reason="氛围章",
                ),
            ],
            chapter_mode="interior",
            style_profile="wang_xiaobo",
            score_summary={"quality": 72},
        )
        prompt = memo_to_revision_prompt(memo)
        self.assertIn("禁止执行", prompt)
        self.assertIn("冲突信号偏弱", prompt)
        self.assertIn("氛围章", prompt)

    def test_finding_contested_by_style_court(self):
        from editor_memo import _finding_contested_by_style_court
        from novel_schemas import StyleCourtDecision

        decision = StyleCourtDecision(
            chapter_number=1,
            is_mock=True,
            contested_issues=[
                {"source": "quality", "issue": "冲突信号偏弱：细节不足",
                 "reason": "氛围章", "finding_key": "k1"},
            ],
        )
        finding = {"item": "冲突信号偏弱", "detail": "细节不足", "finding_key": "k1"}
        self.assertTrue(_finding_contested_by_style_court(finding, decision))
        finding2 = {"item": "对白比例偏高", "detail": "", "finding_key": "k2"}
        self.assertFalse(_finding_contested_by_style_court(finding2, decision))

    def test_empty_memo_no_must_fix(self):
        from editor_memo import memo_to_revision_prompt
        from novel_schemas import EditorMemo

        memo = EditorMemo(
            chapter_number=1,
            overall_assessment="无问题",
            ready_for_final=True,
            is_mock=True,
            top_3_must_fix=[],
            contradictions=[],
            reservations=[],
            score_summary={},
        )
        prompt = memo_to_revision_prompt(memo)
        self.assertIn("暂无必改项", prompt)


class VoiceDiagnosticsPipelineTests(unittest.TestCase):
    """角色声音诊断管线测试"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "04_审核日志").mkdir(parents=True, exist_ok=True)

    def test_voice_fingerprint_model(self):
        from novel_schemas import VoiceFingerprint, CharacterVoiceProfile

        profile = CharacterVoiceProfile(
            character_name="沈逐光",
            avg_sentence_length=12.5,
            dialogue_count=10,
            particle_frequency={"吧": 3.0},
        )
        fp = VoiceFingerprint(
            chapter_number=1,
            profiles=[profile],
            flagged_pairs=[],
        )
        js = fp.model_dump_json()
        loaded = VoiceFingerprint.model_validate_json(js)
        self.assertEqual(loaded.chapter_number, 1)
        self.assertEqual(len(loaded.profiles), 1)
        self.assertEqual(loaded.profiles[0].character_name, "沈逐光")
        self.assertEqual(loaded.profiles[0].avg_sentence_length, 12.5)

    def test_voice_fingerprint_defaults(self):
        from novel_schemas import VoiceFingerprint

        fp = VoiceFingerprint(chapter_number=1)
        self.assertEqual(fp.profiles, [])
        self.assertEqual(fp.flagged_pairs, [])
        self.assertFalse(fp.is_mock)

    def test_analyze_character_voices_mock(self):
        """在 mock 模式下使用临时项目目录测试"""
        import os
        os.environ["NOVEL_LLM_MODE"] = "mock"
        try:
            from voice_diagnostics import analyze_character_voices
            body_dir = self.tmp / "02_正文"
            body_dir.mkdir(exist_ok=True)
            (body_dir / "第001章_草稿.md").write_text(
                "沈逐光道：\"走吧。\"\n\n"
                "郁时谌低声道：\"可是……我还没准备好……\"\n",
                encoding="utf-8")

            result = analyze_character_voices(self.tmp, 1)
            self.assertIsNotNone(result)
        finally:
            os.environ.pop("NOVEL_LLM_MODE", None)


class LiteraryCriticPipelineTests(unittest.TestCase):
    """文学批评管线测试"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "04_审核日志").mkdir(parents=True, exist_ok=True)
        (self.tmp / "02_正文").mkdir(parents=True, exist_ok=True)

    def test_literary_view_model_with_memorable_moments(self):
        from novel_schemas import LiteraryView, MemorableMoment

        view = LiteraryView(
            chapter_number=1,
            cannot_be_quantified=True,
            is_mock=True,
            memorable_moments=[
                MemorableMoment(
                    quote="他在雨中等了三个小时",
                    why_memorable="动作与沉默的张力",
                    fragility="改稿可能删节",
                ),
            ],
            unsaid_tension=["她想说但从未说出口的爱"],
            reader_residue=["读完半小时后还在想那个眼神"],
            moral_ambiguity=["杀坏人算正义吗"],
            self_deception_signals=["她告诉自己并不在乎"],
            literary_risks=["冲突过于内化可能影响追读"],
        )
        js = view.model_dump_json()
        loaded = LiteraryView.model_validate_json(js)
        self.assertEqual(len(loaded.memorable_moments), 1)
        self.assertEqual(loaded.memorable_moments[0].quote, "他在雨中等了三个小时")
        self.assertEqual(len(loaded.moral_ambiguity), 1)
        self.assertEqual(len(loaded.self_deception_signals), 1)

    def test_literary_view_write_read(self):
        from literary_critic import write_literary_view, read_literary_view
        from novel_schemas import LiteraryView, MemorableMoment

        view = LiteraryView(
            chapter_number=1,
            cannot_be_quantified=False,
            is_mock=True,
            memorable_moments=[
                MemorableMoment(quote="测试", why_memorable="测试理由"),
            ],
            unsaid_tension=[],
            reader_residue=[],
            moral_ambiguity=[],
            self_deception_signals=[],
            literary_risks=[],
        )
        json_path, _ = write_literary_view(self.tmp, view)
        self.assertTrue(json_path.exists())

        loaded = read_literary_view(self.tmp, 1)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.chapter_number, 1)
        self.assertEqual(len(loaded.memorable_moments), 1)

    def test_literary_view_empty_moments(self):
        from novel_schemas import LiteraryView

        view = LiteraryView(
            chapter_number=2,
            is_mock=True,
        )
        self.assertEqual(len(view.memorable_moments), 0)
        self.assertFalse(view.cannot_be_quantified)


class DramaticArcPipelineTests(unittest.TestCase):
    """戏剧弧光诊断管线测试"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "04_审核日志").mkdir(parents=True, exist_ok=True)

    def test_drama_diagnostics_model(self):
        from novel_schemas import DramaticDiagnostics

        diag = DramaticDiagnostics(
            chapter_number=1,
            is_mock=True,
            pressure_curve_score=65,
            character_arc_score=50,   # 正确的字段名
            cinematic_score=75,        # 正确的字段名
            overall_drama_score=65,
            top_revision_targets=["章首钩子需要更强"],
        )
        js = diag.model_dump_json()
        loaded = DramaticDiagnostics.model_validate_json(js)
        self.assertEqual(loaded.pressure_curve_score, 65)
        self.assertEqual(loaded.character_arc_score, 50)
        self.assertEqual(loaded.cinematic_score, 75)

    def test_drama_diag_write_read(self):
        from dramatic_arc_diagnostics import write_diagnostics, read_diagnostics
        from novel_schemas import DramaticDiagnostics

        diag = DramaticDiagnostics(
            chapter_number=2,
            is_mock=True,
            pressure_curve_score=80,
            character_arc_score=70,
            cinematic_score=80,
            overall_drama_score=75,
            top_revision_targets=["钩子"],
        )
        json_path, _ = write_diagnostics(self.tmp, diag)
        self.assertTrue(json_path.exists())

        loaded = read_diagnostics(self.tmp, 2)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.chapter_number, 2)


class CrossModuleConsistencyTests(unittest.TestCase):
    """跨模块一致性测试"""

    def test_style_court_and_editor_memo_same_mock_caveat(self):
        """style_court 和 editor_memo 中的 _is_mock_caveat 逻辑一致"""
        from style_court import _is_mock_caveat as sc_caveat
        from editor_memo import _is_mock_caveat as em_caveat

        mock_text = "[Mock] 本数据由占位程序生成，不应把本占位结果当作真实诊断。"
        normal_text = "这是一条正常的文学风险。"

        self.assertTrue(sc_caveat(mock_text))
        self.assertTrue(em_caveat(mock_text))
        self.assertFalse(sc_caveat(normal_text))
        self.assertFalse(em_caveat(normal_text))
