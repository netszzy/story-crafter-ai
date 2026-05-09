"""V5.0-rc1 数据层专项测试：override 三态、schema 往返、序列化边界"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from novel_schemas import DiagnosticReservation, ProjectHealthSnapshot, ChapterHealthSnapshot


class DiagnosticReservationSchemaTests(unittest.TestCase):
    """DiagnosticReservation V5.0-rc1 schema 测试"""

    def test_default_action_is_protect(self):
        r = DiagnosticReservation(rejected_advice="冲突信号偏弱", writer_reason="作家保护")
        self.assertEqual(r.action, "protect")

    def test_action_adopt(self):
        r = DiagnosticReservation(
            action="adopt",
            rejected_advice="对白比例偏高",
            writer_reason="同意，下次改稿执行",
        )
        self.assertEqual(r.action, "adopt")

    def test_action_rebut(self):
        r = DiagnosticReservation(
            action="rebut",
            rejected_advice="角色主动性偏弱",
            writer_reason="郁时谌此时处于内省状态，被动是人物性格使然",
        )
        self.assertEqual(r.action, "rebut")

    def test_json_roundtrip_preserves_action(self):
        r = DiagnosticReservation(
            action="rebut",
            diagnostic_source="quality",
            rejected_advice="冲突信号偏弱",
            writer_reason="氛围章不计冲突",
            finding_key="conflict_signal_weak",
        )
        js = r.model_dump_json()
        loaded = DiagnosticReservation.model_validate_json(js)
        self.assertEqual(loaded.action, "rebut")
        self.assertEqual(loaded.rejected_advice, "冲突信号偏弱")
        self.assertEqual(loaded.finding_key, "conflict_signal_weak")

    def test_backward_compat_missing_action_defaults_to_protect(self):
        """旧记录（无 action 字段）反序列化后 action 应为 protect"""
        old_json = json.dumps({
            "diagnostic_source": "quality",
            "rejected_advice": "冲突信号偏弱",
            "writer_reason": "氛围章",
            "finding_key": "",
        })
        loaded = DiagnosticReservation.model_validate_json(old_json)
        self.assertEqual(loaded.action, "protect")

    def test_invalid_action_rejected(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            DiagnosticReservation(
                action="delete",  # 不在 Literal["adopt","protect","rebut"] 中
                rejected_advice="x",
            )

    def test_finding_key_default(self):
        r = DiagnosticReservation(rejected_advice="test", writer_reason="reason")
        self.assertEqual(r.finding_key, "")

    def test_created_at_auto_generated(self):
        r = DiagnosticReservation(rejected_advice="test", writer_reason="reason")
        self.assertIsNotNone(r.created_at)
        self.assertIn("T", r.created_at)  # ISO 8601 格式


class ProjectHealthSnapshotSchemaTests(unittest.TestCase):
    """ProjectHealthSnapshot V5.0-rc1 schema 测试"""

    def test_default_values(self):
        snap = ProjectHealthSnapshot()
        self.assertEqual(snap.total_chapters_diagnosed, 0)
        self.assertEqual(snap.total_chapters, 0)
        self.assertEqual(snap.engineering_sturdiness, 0.0)
        self.assertEqual(snap.literary_density, 0.0)
        self.assertEqual(snap.style_consistency, 0.0)
        self.assertEqual(snap.engineering_trend, "stable")
        self.assertEqual(snap.literary_trend, "stable")
        self.assertEqual(snap.style_trend, "stable")
        self.assertIsNone(snap.weakest_chapter_engineering)
        self.assertIsNone(snap.weakest_chapter_literary)
        self.assertIsNone(snap.most_style_drifted_chapter)
        self.assertEqual(snap.chapter_snapshots, [])

    def test_json_roundtrip(self):
        snap = ProjectHealthSnapshot(
            total_chapters_diagnosed=5,
            total_chapters=10,
            engineering_sturdiness=72.5,
            literary_density=42.0,
            style_consistency=85.0,
            engineering_trend="improving",
            weakest_chapter_engineering=7,
            weakest_chapter_literary=3,
            most_style_drifted_chapter=4,
        )
        js = snap.model_dump_json()
        loaded = ProjectHealthSnapshot.model_validate_json(js)
        self.assertEqual(loaded.engineering_sturdiness, 72.5)
        self.assertEqual(loaded.literary_density, 42.0)
        self.assertEqual(loaded.style_consistency, 85.0)
        self.assertEqual(loaded.engineering_trend, "improving")
        self.assertEqual(loaded.weakest_chapter_engineering, 7)

    def test_chapter_health_snapshot(self):
        ch = ChapterHealthSnapshot(
            chapter_number=1,
            score_quality=80,
            literary_density=40.0,
            style_consistency=100.0,
            has_draft=True,
        )
        self.assertEqual(ch.score_quality, 80)
        self.assertTrue(ch.has_draft)

    def test_chapter_health_snapshot_defaults(self):
        ch = ChapterHealthSnapshot(chapter_number=1)
        self.assertIsNone(ch.score_quality)
        self.assertEqual(ch.literary_density, 0.0)
        self.assertEqual(ch.style_consistency, 0.0)
        self.assertFalse(ch.has_draft)


class WriteWriterOverrideTests(unittest.TestCase):
    """write_writer_override V5.0-rc1 三态测试"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.project_dir = Path(self.tmp)
        log_dir = self.project_dir / "04_审核日志"
        log_dir.mkdir(parents=True, exist_ok=True)

    def _import_quality(self):
        from quality_diagnostics import (
            write_writer_override,
            read_writer_overrides,
            apply_writer_overrides,
        )
        return write_writer_override, read_writer_overrides, apply_writer_overrides

    def test_write_with_keyword_args_adopt(self):
        write_writer_override, read_writer_overrides, _ = self._import_quality()
        write_writer_override(
            self.project_dir, 1,
            rejected_advice="冲突信号偏弱",
            writer_reason="作家采纳，下次改稿执行",
            action="adopt",
        )
        overrides = read_writer_overrides(self.project_dir, 1)
        self.assertGreaterEqual(len(overrides), 1)
        self.assertEqual(overrides[0]["action"], "adopt")

    def test_write_with_keyword_args_protect(self):
        write_writer_override, read_writer_overrides, _ = self._import_quality()
        write_writer_override(
            self.project_dir, 1,
            rejected_advice="对白比例偏高",
            writer_reason="氛围章，对话少是风格需要",
            action="protect",
        )
        overrides = read_writer_overrides(self.project_dir, 1)
        self.assertGreaterEqual(len(overrides), 1)
        self.assertEqual(overrides[0]["action"], "protect")

    def test_write_with_keyword_args_rebut(self):
        write_writer_override, read_writer_overrides, _ = self._import_quality()
        write_writer_override(
            self.project_dir, 1,
            rejected_advice="角色主动性偏弱",
            writer_reason="内省状态，被动是人物性格使然",
            action="rebut",
        )
        overrides = read_writer_overrides(self.project_dir, 1)
        self.assertGreaterEqual(len(overrides), 1)
        self.assertEqual(overrides[0]["action"], "rebut")

    def test_apply_writer_overrides_three_actions(self):
        """测试三种 action 对 findings 的不同影响"""
        write_writer_override, read_writer_overrides, apply_writer_overrides = self._import_quality()

        # 创建三条 override
        write_writer_override(self.project_dir, 1,
            rejected_advice="冲突信号偏弱", writer_reason="采纳",
            action="adopt")
        write_writer_override(self.project_dir, 1,
            rejected_advice="对白比例偏高", writer_reason="保护",
            action="protect")
        write_writer_override(self.project_dir, 1,
            rejected_advice="角色主动性偏弱", writer_reason="反驳",
            action="rebut")

        overrides = read_writer_overrides(self.project_dir, 1)

        # 构造模拟 findings
        findings = [
            {"level": "warning", "item": "冲突信号偏弱", "detail": "本章冲突不足"},
            {"level": "warning", "item": "对白比例偏高", "detail": "对话占比略高"},
            {"level": "warning", "item": "角色主动性偏弱", "detail": "主角缺乏主动行为"},
            {"level": "info", "item": "其他发现", "detail": "无影响"},
        ]
        report = {"findings": findings, "score": 65}

        result = apply_writer_overrides(report, overrides)

        # adopt: finding 应保持原 level（不被标记为 accepted）
        # protect: finding 应标记为 accepted_by_writer
        # rebut: finding 应标记为 rebutted_by_writer
        result_levels = {f.get("item", ""): f.get("level", "") for f in result.get("findings", [])}
        self.assertEqual(result_levels.get("对白比例偏高"), "accepted_by_writer")
        self.assertEqual(result_levels.get("角色主动性偏弱"), "rebutted_by_writer")
        # adopt 保持原 level
        self.assertEqual(result_levels.get("冲突信号偏弱"), "warning")
        # adopt 应记录 writer_action
        adopt_finding = [f for f in result["findings"] if f["item"] == "冲突信号偏弱"][0]
        self.assertEqual(adopt_finding.get("writer_action"), "adopt")

    def test_apply_writer_overrides_score_refund(self):
        """protect 和 rebut 应退款分数，adopt 不退款"""
        write_writer_override, read_writer_overrides, apply_writer_overrides = self._import_quality()

        # adopt 不退款 — 冲突信号偏弱 penalty=10（来自 FINDING_SCORE_PENALTIES）
        write_writer_override(self.project_dir, 2,
            rejected_advice="冲突信号偏弱", writer_reason="采纳",
            action="adopt")
        # protect 退款 — 对白比例偏高 penalty=8
        write_writer_override(self.project_dir, 2,
            rejected_advice="对白比例偏高", writer_reason="保护",
            action="protect")
        # rebut 退款 — 角色主动性偏弱 penalty=8
        write_writer_override(self.project_dir, 2,
            rejected_advice="角色主动性偏弱", writer_reason="反驳",
            action="rebut")

        overrides = read_writer_overrides(self.project_dir, 2)

        # 使用与 FINDING_SCORE_PENALTIES 匹配的 item 名
        findings = [
            {"level": "warning", "item": "冲突信号偏弱"},
            {"level": "warning", "item": "对白比例偏高"},
            {"level": "warning", "item": "角色主动性偏弱"},
        ]
        report = {"findings": findings, "score": 65}

        result = apply_writer_overrides(report, overrides)
        # adopt 不退分
        # protect 退款 8（对白比例偏高），rebut 退款 8（角色主动性偏弱）= 16
        new_score = result.get("score", 65)
        self.assertGreater(new_score, 65)  # 分数应回升
        self.assertEqual(new_score, 81)  # 65 + 8 + 8
        self.assertEqual(result.get("score_before_writer_overrides"), 65)

    def test_deduplication_by_finding_key(self):
        """相同 finding_key 的 override 应去重，保留最新的"""
        write_writer_override, read_writer_overrides, _ = self._import_quality()

        write_writer_override(self.project_dir, 3,
            rejected_advice="旧建议", writer_reason="旧理由",
            action="protect", finding_key="same_key")
        write_writer_override(self.project_dir, 3,
            rejected_advice="新建议", writer_reason="新理由",
            action="rebut", finding_key="same_key")

        overrides = read_writer_overrides(self.project_dir, 3)
        matching = [o for o in overrides if o.get("finding_key") == "same_key"]
        # 应只有一条（最新的覆盖了旧的）
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["action"], "rebut")
        self.assertEqual(matching[0]["writer_reason"], "新理由")

    def test_deduplication_by_rejected_advice(self):
        """相同 rejected_advice 而无 finding_key 的也应去重"""
        write_writer_override, read_writer_overrides, _ = self._import_quality()

        write_writer_override(self.project_dir, 4,
            rejected_advice="对白比例偏高", writer_reason="理由1",
            action="protect")
        write_writer_override(self.project_dir, 4,
            rejected_advice="对白比例偏高", writer_reason="理由2",
            action="adopt")

        overrides = read_writer_overrides(self.project_dir, 4)
        matching = [o for o in overrides if o.get("rejected_advice") == "对白比例偏高"]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching[0]["action"], "adopt")


class ActiveFindingsFilterTests(unittest.TestCase):
    """style_court._active_findings 和 quality_diagnostics._active_findings 过滤测试"""

    def test_style_court_filters_both_accepted_and_rebutted(self):
        from style_court import _active_findings

        report = {
            "findings": [
                {"level": "error", "item": "逻辑矛盾"},
                {"level": "accepted_by_writer", "item": "冲突信号偏弱"},
                {"level": "rebutted_by_writer", "item": "角色主动性偏弱"},
                {"level": "warning", "item": "对白比例偏高"},
                {"level": "accepted_by_writer", "item": "动作密度低"},
            ]
        }
        active = _active_findings(report)
        self.assertEqual(len(active), 2)
        items = {f["item"] for f in active}
        self.assertIn("逻辑矛盾", items)
        self.assertIn("对白比例偏高", items)
        self.assertNotIn("冲突信号偏弱", items)
        self.assertNotIn("角色主动性偏弱", items)

    def test_quality_active_findings_filters_both(self):
        from quality_diagnostics import _active_findings as q_active

        # quality_diagnostics._active_findings 接收 list，不是 report dict
        findings = [
            {"level": "error", "item": "逻辑矛盾"},
            {"level": "accepted_by_writer", "item": "冲突信号偏弱"},
            {"level": "rebutted_by_writer", "item": "角色主动性偏弱"},
        ]
        active = q_active(findings)
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["item"], "逻辑矛盾")

    def test_empty_report(self):
        from style_court import _active_findings
        self.assertEqual(_active_findings(None), [])
        self.assertEqual(_active_findings({}), [])

    def test_no_findings_key(self):
        from style_court import _active_findings
        self.assertEqual(_active_findings({"other": "data"}), [])


class EditorMemoReservationsMergeTests(unittest.TestCase):
    """_merge_reservations V5.0-rc1 过滤测试"""

    def test_adopt_entries_skipped(self):
        from editor_memo import _merge_reservations

        reservations = [
            {"action": "adopt", "diagnostic_source": "quality",
             "rejected_advice": "冲突信号偏弱", "writer_reason": "采纳"},
            {"action": "protect", "diagnostic_source": "quality",
             "rejected_advice": "对白比例偏高", "writer_reason": "保护"},
            {"action": "rebut", "diagnostic_source": "quality",
             "rejected_advice": "角色主动性偏弱", "writer_reason": "反驳"},
        ]
        merged = _merge_reservations(reservations,
                                     literary_view=None,
                                     style_court_decision=None)
        advices = {m["rejected_advice"] for m in merged}
        self.assertNotIn("冲突信号偏弱", advices)
        self.assertIn("对白比例偏高", advices)
        self.assertIn("角色主动性偏弱", advices)

    def test_old_records_default_to_protect(self):
        """旧记录（无 action 字段）应被保留并视为 protect"""
        from editor_memo import _merge_reservations

        # 模拟旧格式：没有 action 字段
        old_reservation = {
            "diagnostic_source": "quality",
            "rejected_advice": "冲突信号偏弱",
            "writer_reason": "氛围章",
        }
        merged = _merge_reservations([old_reservation],
                                     literary_view=None,
                                     style_court_decision=None)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["rejected_advice"], "冲突信号偏弱")

    def test_empty_rejected_advice_skipped(self):
        from editor_memo import _merge_reservations

        reservations = [
            {"action": "protect", "diagnostic_source": "quality",
             "rejected_advice": "", "writer_reason": "空"},
        ]
        merged = _merge_reservations(reservations,
                                     literary_view=None,
                                     style_court_decision=None)
        self.assertEqual(len(merged), 0)


class ProjectHealthComputeTests(unittest.TestCase):
    """compute_project_health V5.0-rc1 计算测试"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.project_dir = Path(self.tmp)
        log_dir = self.project_dir / "04_审核日志"
        log_dir.mkdir(parents=True, exist_ok=True)
        body_dir = self.project_dir / "02_正文"
        body_dir.mkdir(parents=True, exist_ok=True)

    def test_empty_project_returns_default(self):
        from project_center import compute_project_health

        health = compute_project_health(self.project_dir)
        self.assertEqual(health.total_chapters_diagnosed, 0)
        self.assertEqual(health.engineering_sturdiness, 0.0)

    def test_computes_from_quality_reports(self):
        from project_center import compute_project_health

        # 创建质量诊断文件
        for ch in range(1, 4):
            q_data = {"overall_score": 70 + ch * 5}
            (self.project_dir / "04_审核日志" / f"第{ch:03d}章_质量诊断.json").write_text(
                json.dumps(q_data, ensure_ascii=False))

        # 创建草稿
        for ch in range(1, 4):
            (self.project_dir / "02_正文" / f"第{ch:03d}章_草稿.md").write_text("测试正文")

        health = compute_project_health(self.project_dir)
        self.assertEqual(health.total_chapters_diagnosed, 3)
        # mean of 75, 80, 85 = 80
        self.assertAlmostEqual(health.engineering_sturdiness, 80.0, places=1)

    def test_literary_density_from_memorable_moments(self):
        from project_center import compute_project_health

        for ch in range(1, 3):
            (self.project_dir / "02_正文" / f"第{ch:03d}章_草稿.md").write_text("测试正文")
            q_data = {"overall_score": 80}
            (self.project_dir / "04_审核日志" / f"第{ch:03d}章_质量诊断.json").write_text(
                json.dumps(q_data, ensure_ascii=False))
            # ch1: 2 memorable moments, ch2: 4 memorable moments
            lit_data = {"memorable_moments": ["m1"] * (ch * 2)}
            (self.project_dir / "04_审核日志" / f"第{ch:03d}章_文学批评.json").write_text(
                json.dumps(lit_data, ensure_ascii=False))

        health = compute_project_health(self.project_dir)
        # ch1: 2/5*100 = 40, ch2: 4/5*100 = 80, mean = 60
        self.assertAlmostEqual(health.literary_density, 60.0, places=1)

    def test_style_consistency_from_flagged_pairs(self):
        from project_center import compute_project_health

        for ch in range(1, 3):
            (self.project_dir / "02_正文" / f"第{ch:03d}章_草稿.md").write_text("测试正文")
            q_data = {"overall_score": 80}
            (self.project_dir / "04_审核日志" / f"第{ch:03d}章_质量诊断.json").write_text(
                json.dumps(q_data, ensure_ascii=False))
            # ch1: 1 flagged pair → 80, ch2: 3 flagged pairs → 40
            voice_data = {"flagged_pairs": [{}] * (ch * 2 - 1)}
            (self.project_dir / "04_审核日志" / f"第{ch:03d}章_声音诊断.json").write_text(
                json.dumps(voice_data, ensure_ascii=False))

        health = compute_project_health(self.project_dir)
        # ch1: 100 - 1*20 = 80, ch2: 100 - 3*20 = 40, mean = 60
        self.assertAlmostEqual(health.style_consistency, 60.0, places=1)

    def test_weakest_chapter_identification(self):
        from project_center import compute_project_health

        for ch, score in [(1, 90), (2, 60), (3, 75)]:
            (self.project_dir / "02_正文" / f"第{ch:03d}章_草稿.md").write_text("测试正文")
            q_data = {"overall_score": score}
            (self.project_dir / "04_审核日志" / f"第{ch:03d}章_质量诊断.json").write_text(
                json.dumps(q_data, ensure_ascii=False))

        health = compute_project_health(self.project_dir)
        self.assertEqual(health.weakest_chapter_engineering, 2)

    def test_corrupt_json_graceful_degradation(self):
        from project_center import compute_project_health

        # quality JSON 不可解析 → 该章仍会被统计但 eng_score 为 0.0
        (self.project_dir / "02_正文" / "第001章_草稿.md").write_text("测试正文")
        (self.project_dir / "04_审核日志" / "第001章_质量诊断.json").write_text("not valid json")

        # 不应抛出异常
        health = compute_project_health(self.project_dir)
        self.assertIsNotNone(health)
        # 文件存在仍会加入 snapshots，但 eng_score 为 0.0
        self.assertEqual(health.total_chapters_diagnosed, 1)
        self.assertEqual(health.engineering_sturdiness, 0.0)


class ScrollHealthThreeDimensionTests(unittest.TestCase):
    """scroll_health V5.0-rc1 三维数据收集测试"""

    def test_score_to_scroll_color_cream_to_brown(self):
        from webui_infra.components.scroll_health import score_to_scroll_color

        # 高分（100）应接近奶油色
        high = score_to_scroll_color(100)
        self.assertIn("#", high)

        # 低分（0）应接近深棕色
        low = score_to_scroll_color(0)
        self.assertIn("#", low)

        # 高分和低分应产生不同的颜色
        self.assertNotEqual(high, low)

    def test_score_none_returns_no_data_color(self):
        from webui_infra.components.scroll_health import score_to_scroll_color, NO_DATA
        self.assertEqual(score_to_scroll_color(None), NO_DATA)

    def test_score_clamped_to_0_100(self):
        from webui_infra.components.scroll_health import score_to_scroll_color

        # 超出范围的值应被 clamp
        c1 = score_to_scroll_color(150)
        c2 = score_to_scroll_color(-50)
        self.assertIsNotNone(c1)
        self.assertIsNotNone(c2)
        # 150 clamp 到 100 → 奶油色, -50 clamp 到 0 → 深棕色
        self.assertEqual(c1, score_to_scroll_color(100))
        self.assertEqual(c2, score_to_scroll_color(0))

    def test_scroll_health_chapter_per_dimension_scores(self):
        from webui_infra.components.scroll_health import ScrollHealthChapter

        ch = ScrollHealthChapter(
            chapter_number=1,
            score=80,
            source="质量",
            color="#abc",
            summary="测试",
            worst_diagnostic="",
            keeper_quote="",
            has_draft=True,
            score_engineering=80,
            score_literary=60,
            score_style=40,
        )
        self.assertEqual(ch.score_for_dimension("engineering"), 80)
        self.assertEqual(ch.score_for_dimension("literary"), 60)
        self.assertEqual(ch.score_for_dimension("style"), 40)

    def test_weakest_chapter_by_dimension(self):
        from webui_infra.components.scroll_health import ScrollHealthChapter, weakest_chapter

        chapters = [
            ScrollHealthChapter(1, 80, "质量", "#x", "", "", "", True,
                               score_engineering=80, score_literary=60, score_style=90),
            ScrollHealthChapter(2, 60, "质量", "#x", "", "", "", True,
                               score_engineering=60, score_literary=40, score_style=70),
            ScrollHealthChapter(3, 70, "质量", "#x", "", "", "", True,
                               score_engineering=70, score_literary=80, score_style=50),
        ]
        self.assertEqual(weakest_chapter(chapters, "engineering").chapter_number, 2)
        self.assertEqual(weakest_chapter(chapters, "literary").chapter_number, 2)
        self.assertEqual(weakest_chapter(chapters, "style").chapter_number, 3)

    def test_weakest_chapter_ignores_none_scores(self):
        from webui_infra.components.scroll_health import ScrollHealthChapter, weakest_chapter

        chapters = [
            ScrollHealthChapter(1, None, "", "#x", "", "", "", True,
                               score_engineering=None, score_literary=60),
            ScrollHealthChapter(2, 80, "", "#x", "", "", "", True,
                               score_engineering=80, score_literary=40),
        ]
        self.assertEqual(weakest_chapter(chapters, "engineering").chapter_number, 2)
        # 只有 ch2 有 score_literary
        self.assertEqual(weakest_chapter(chapters, "literary").chapter_number, 2)
