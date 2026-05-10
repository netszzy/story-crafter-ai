"""V5.0-rc1 集成与边界测试：跨模块数据流、状态一致性、边界条件"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


class CrossModuleDataFlowTests(unittest.TestCase):
    """跨模块完整数据流测试"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        for d in ["02_正文", "04_审核日志", "01_大纲/章纲"]:
            (self.tmp / d).mkdir(parents=True, exist_ok=True)

    def test_quality_to_style_court_to_editor_memo_full_flow(self):
        """完整链路：质量诊断 → 风格法庭裁决 → 编辑备忘录合并 reservations"""
        from quality_diagnostics import write_writer_override, read_writer_overrides, apply_writer_overrides
        from style_court import adjudicate, contested_to_reservations
        from editor_memo import _merge_reservations
        from novel_schemas import LiteraryView

        # 1. 构造模拟质量诊断报告（18条 findings 的典型场景）
        report = {
            "findings": [
                {"level": "error", "item": "逻辑矛盾", "detail": "时间线断裂",
                 "score_penalty": 15},
                {"level": "warning", "item": "冲突信号偏弱", "detail": "冲突不足",
                 "score_penalty": 10},
                {"level": "warning", "item": "角色主动性偏弱", "detail": "主角被动",
                 "score_penalty": 8},
                {"level": "warning", "item": "对白比例偏高", "detail": "对话占比高",
                 "score_penalty": 8},
                {"level": "info", "item": "可感细节偏少", "detail": "",
                 "score_penalty": 6},
            ],
            "score": 60,
            "task_card_alignment": {"chapter_mode": "interior", "style_profile": "wang_xiaobo"},
        }

        # 2. 作家对"冲突信号偏弱"和"角色主动性偏弱"做保护裁决
        write_writer_override(self.tmp, 1,
            rejected_advice="冲突信号偏弱", writer_reason="氛围章不适用冲突标准",
            action="protect", finding_key="conflict_weak")
        write_writer_override(self.tmp, 1,
            rejected_advice="角色主动性偏弱", writer_reason="人物被动符合内省状态",
            action="rebut", finding_key="agency_weak")

        # 3. 应用 override → 两条 finding 被标记
        overrides = read_writer_overrides(self.tmp, 1)
        report = apply_writer_overrides(report, overrides)

        # 4. 文学批评层 — 不可量化（氛围章）
        lit = LiteraryView(
            chapter_number=1,
            cannot_be_quantified=True, is_mock=True,
            memorable_moments=[], unsaid_tension=[], reader_residue=[],
            moral_ambiguity=[], self_deception_signals=[], literary_risks=[
                "冲突过于内化可能影响追读",
            ],
        )

        # 5. 风格法庭裁决
        decision = adjudicate(self.tmp, 1, report, lit, None)

        # 验证: error 是 hard issue → confirmed
        # 冲突信号偏弱 → accepted_by_writer → 被 _active_findings 过滤 → 不进法庭
        # 角色主动性偏弱 → rebutted_by_writer → 被 _active_findings 过滤 → 不进法庭
        # 对白比例偏高 → warning + soft → protected → contested
        self.assertGreaterEqual(len(decision.confirmed_issues), 1)  # error 确认
        # literary_risks → contested
        self.assertGreaterEqual(len(decision.contested_issues), 1)

        # 6. 风格法庭 contested → reservations
        court_res = contested_to_reservations(decision)

        # 7. 已有 overrides + court contested → 合并 reservations
        merged = _merge_reservations(overrides,
                                     literary_view=lit,
                                     style_court_decision=decision)
        # merged 应包含：protect 裁决(1) + rebut 裁决(1) + literary_risks(1) + court contested
        self.assertGreaterEqual(len(merged), 3)

        # adopt 不应出现（因为没写 adopt override）
        actions = {m.get("action") for m in merged}
        self.assertNotIn("adopt", actions)

    def test_writer_override_affects_downstream_must_fix(self):
        """作家保护/反驳后的 finding 不再进入 must_fix（通过 _active_findings 过滤）"""
        from quality_diagnostics import write_writer_override, read_writer_overrides, apply_writer_overrides
        from style_court import _active_findings

        write_writer_override(self.tmp, 2,
            rejected_advice="冲突信号偏弱", writer_reason="保护",
            action="protect")
        write_writer_override(self.tmp, 2,
            rejected_advice="角色主动性偏弱", writer_reason="反驳",
            action="rebut")

        overrides = read_writer_overrides(self.tmp, 2)
        report = {
            "findings": [
                {"level": "error", "item": "逻辑矛盾", "score_penalty": 15},
                {"level": "warning", "item": "冲突信号偏弱", "score_penalty": 10},
                {"level": "warning", "item": "角色主动性偏弱", "score_penalty": 8},
                {"level": "info", "item": "可感细节偏少", "score_penalty": 6},
            ],
            "score": 70,
        }
        result = apply_writer_overrides(report, overrides)

        # _active_findings 应过滤掉 accepted_by_writer 和 rebutted_by_writer
        active = _active_findings(result)
        self.assertEqual(len(active), 2)
        items = {f["item"] for f in active}
        self.assertIn("逻辑矛盾", items)
        self.assertIn("可感细节偏少", items)
        self.assertNotIn("冲突信号偏弱", items)
        self.assertNotIn("角色主动性偏弱", items)

        # 分数应退款 10+8=18 → 88
        self.assertEqual(result["score"], 88)

    def test_adopt_flow_stays_active_not_filtered(self):
        """采纳的 finding 保持活跃，不被 _active_findings 过滤"""
        from quality_diagnostics import write_writer_override, read_writer_overrides, apply_writer_overrides
        from quality_diagnostics import _active_findings as q_active

        write_writer_override(self.tmp, 3,
            rejected_advice="对白比例偏高", writer_reason="同意修改",
            action="adopt")

        overrides = read_writer_overrides(self.tmp, 3)
        report = {
            "findings": [
                {"level": "warning", "item": "对白比例偏高", "score_penalty": 8},
                {"level": "warning", "item": "可感细节偏少", "score_penalty": 6},
            ],
            "score": 70,
        }
        result = apply_writer_overrides(report, overrides)

        # adopt → 不进入 accepted_by_writer，保持原 level
        active = q_active(result["findings"])
        self.assertEqual(len(active), 2)  # 两条都活跃

        # adopt → 不退分
        self.assertEqual(result["score"], 70)

    def test_project_health_aggregates_from_all_chapters(self):
        """项目健康从多章数据聚合三维指标"""
        from project_center import compute_project_health

        for ch in range(1, 6):
            (self.tmp / "02_正文" / f"第{ch:03d}章_草稿.md").write_text("正文内容")
            q = {"overall_score": 60 + ch * 5}
            (self.tmp / "04_审核日志" / f"第{ch:03d}章_质量诊断.json").write_text(
                json.dumps(q, ensure_ascii=False))
            lit = {"memorable_moments": ["m" + str(i) for i in range(ch)]}
            (self.tmp / "04_审核日志" / f"第{ch:03d}章_文学批评.json").write_text(
                json.dumps(lit, ensure_ascii=False))
            voice = {"flagged_pairs": [{}] * (ch % 3)}
            (self.tmp / "04_审核日志" / f"第{ch:03d}章_声音指纹.json").write_text(
                json.dumps(voice, ensure_ascii=False))

        health = compute_project_health(self.tmp)
        self.assertEqual(health.total_chapters_diagnosed, 5)
        # engineering: mean of 65+70+75+80+85 = 75
        # 但 score 在 JSON 中是 overall_score，eng_score 用的是 overall_score or score
        # Verify: ch1: 65, ch2: 70, ch3: 75, ch4: 80, ch5: 85 → mean = 75
        self.assertAlmostEqual(health.engineering_sturdiness, 75.0, places=0)
        # literary: ch1:1/5*100=20, ch2:40, ch3:60, ch4:80, ch5:100 → mean=60
        self.assertAlmostEqual(health.literary_density, 60.0, places=0)

        # weakest chapters
        self.assertEqual(health.weakest_chapter_engineering, 1)
        self.assertEqual(health.weakest_chapter_literary, 1)

    def test_scroll_health_dimension_switching(self):
        """scroll_health 三维数据收集与切换"""
        from webui_infra.components.scroll_health import ScrollHealthChapter, weakest_chapter

        chapters = [
            ScrollHealthChapter(1, 80, "质量", "", "s1", "", "", True,
                               score_engineering=80, score_literary=30, score_style=90),
            ScrollHealthChapter(2, 50, "质量", "", "s2", "", "", True,
                               score_engineering=50, score_literary=80, score_style=30),
            ScrollHealthChapter(3, 70, "质量", "", "s3", "", "", True,
                               score_engineering=70, score_literary=50, score_style=60),
        ]

        # 每维度最弱章不同
        self.assertEqual(weakest_chapter(chapters, "engineering").chapter_number, 2)
        self.assertEqual(weakest_chapter(chapters, "literary").chapter_number, 1)
        self.assertEqual(weakest_chapter(chapters, "style").chapter_number, 2)

        # score_for_dimension 测试
        self.assertEqual(chapters[0].score_for_dimension("engineering"), 80)
        self.assertEqual(chapters[0].score_for_dimension("literary"), 30)
        self.assertEqual(chapters[0].score_for_dimension("style"), 90)


class BoundaryConditionTests(unittest.TestCase):
    """边界条件与错误路径测试"""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        for d in ["04_审核日志", "02_正文"]:
            (self.tmp / d).mkdir(parents=True, exist_ok=True)

    def test_chapter_number_zero(self):
        """第0章边界"""
        from quality_diagnostics import write_writer_override, read_writer_overrides

        write_writer_override(self.tmp, 0,
            rejected_advice="测试", writer_reason="测试", action="protect")
        overrides = read_writer_overrides(self.tmp, 0)
        self.assertGreaterEqual(len(overrides), 1)

    def test_chapter_number_999(self):
        """大章号"""
        from quality_diagnostics import write_writer_override, read_writer_overrides

        write_writer_override(self.tmp, 999,
            rejected_advice="测试", writer_reason="测试", action="protect")
        overrides = read_writer_overrides(self.tmp, 999)
        self.assertGreaterEqual(len(overrides), 1)

    def test_empty_report_apply_overrides(self):
        """空报告应用 overrides"""
        from quality_diagnostics import apply_writer_overrides

        overrides = [{"action": "protect", "rejected_advice": "x", "writer_reason": "y"}]
        result = apply_writer_overrides({}, overrides)
        # 空报告无 findings → 提前返回，不添加任何键
        self.assertEqual(result, {})

    def test_no_findings_key_in_report(self):
        """报告中没有 findings 键"""
        from quality_diagnostics import apply_writer_overrides

        overrides = [{"action": "protect", "rejected_advice": "x", "writer_reason": "y"}]
        result = apply_writer_overrides({"score": 80}, overrides)
        # 不应抛出异常
        self.assertIsNotNone(result)

    def test_findings_not_a_list(self):
        """findings 不是 list 时不变更"""
        from quality_diagnostics import apply_writer_overrides

        overrides = [{"action": "protect", "rejected_advice": "x", "writer_reason": "y"}]
        report = {"findings": "not a list", "score": 80}
        result = apply_writer_overrides(report, overrides)
        # 应返回原报告
        self.assertEqual(result, report)

    def test_override_with_empty_rejected_advice(self):
        """空 rejected_advice 的 override 应被拒绝写入"""
        from quality_diagnostics import write_writer_override, read_writer_overrides

        write_writer_override(self.tmp, 10,
            rejected_advice="", writer_reason="空的", action="protect")

        overrides = read_writer_overrides(self.tmp, 10)
        # 修复后：空 advice 被拒绝，不产生任何记录
        self.assertEqual(len(overrides), 0)

    def test_unicode_in_writer_reason(self):
        """作家理由含特殊 Unicode 字符"""
        from quality_diagnostics import write_writer_override, read_writer_overrides

        reason_with_unicode = '氛围章——尤其"涩澤"这种写法需要保留✨'
        write_writer_override(self.tmp, 11,
            rejected_advice="冲突信号偏弱", writer_reason=reason_with_unicode,
            action="protect")

        overrides = read_writer_overrides(self.tmp, 11)
        self.assertGreaterEqual(len(overrides), 1)
        self.assertIn("涩澤", overrides[0]["writer_reason"])

    def test_score_to_scroll_color_boundaries(self):
        """卷轴健康色标极端值"""
        from webui_infra.components.scroll_health import score_to_scroll_color

        # 边界值
        c0 = score_to_scroll_color(0)
        c100 = score_to_scroll_color(100)
        c50 = score_to_scroll_color(50)
        c_negative = score_to_scroll_color(-10)  # 应 clamp 到 0
        c_over = score_to_scroll_color(200)       # 应 clamp 到 100

        self.assertIsNotNone(c0)
        self.assertIsNotNone(c100)
        self.assertEqual(c_negative, c0)
        self.assertEqual(c_over, c100)
        self.assertNotEqual(c0, c100)  # 极值应产生不同颜色

    def test_empty_project_health(self):
        """空项目健康快照"""
        from project_center import compute_project_health

        health = compute_project_health(self.tmp)
        self.assertEqual(health.total_chapters, 0)
        self.assertIsNone(health.weakest_chapter_engineering)
        self.assertEqual(health.engineering_trend, "stable")

    def test_missing_literary_and_voice_files(self):
        """文学批评和声音指纹文件缺失时的降级"""
        from project_center import compute_project_health

        (self.tmp / "02_正文" / "第001章_草稿.md").write_text("正文")
        (self.tmp / "04_审核日志" / "第001章_质量诊断.json").write_text(
            json.dumps({"overall_score": 80}))

        # 没有文学批评和声音指纹文件
        health = compute_project_health(self.tmp)
        self.assertEqual(health.total_chapters_diagnosed, 1)
        self.assertAlmostEqual(health.engineering_sturdiness, 80.0)
        # 缺少文件时应为 0
        self.assertAlmostEqual(health.literary_density, 0.0)
        self.assertAlmostEqual(health.style_consistency, 100.0)  # 0 flagged → 100

    def test_read_writer_overrides_missing_file(self):
        """读取不存在的作家裁决文件"""
        from quality_diagnostics import read_writer_overrides

        overrides = read_writer_overrides(self.tmp, 99)
        self.assertEqual(overrides, [])

    def test_read_style_court_missing_file(self):
        """读取不存在的风格法庭文件"""
        from style_court import read_style_court

        decision = read_style_court(self.tmp, 99)
        self.assertIsNone(decision)

    def test_read_memo_missing_file(self):
        """读取不存在的备忘录文件"""
        from editor_memo import read_memo

        memo = read_memo(self.tmp, 99)
        self.assertIsNone(memo)

    def test_contested_to_reservations_none(self):
        """None decision → 空 reservations"""
        from style_court import contested_to_reservations

        res = contested_to_reservations(None)
        self.assertEqual(res, [])

    def test_memo_to_revision_prompt_empty_top_3(self):
        """top_3_must_fix 为空时短路径"""
        from editor_memo import memo_to_revision_prompt
        from novel_schemas import EditorMemo

        memo = EditorMemo(
            chapter_number=1, overall_assessment="良好",
            ready_for_final=True, is_mock=True,
            top_3_must_fix=[], contradictions=[], reservations=[],
            score_summary={},
        )
        prompt = memo_to_revision_prompt(memo)
        self.assertEqual(prompt, "## 编辑备忘录\n\n暂无必改项，保持当前版本。")

    def test_multiple_writes_same_chapter_override_deduplication(self):
        """同一章多次写入 overrides 的去重行为"""
        from quality_diagnostics import write_writer_override, read_writer_overrides

        for i in range(5):
            write_writer_override(self.tmp, 12,
                rejected_advice="冲突信号偏弱", writer_reason=f"理由{i}",
                action="protect")

        overrides = read_writer_overrides(self.tmp, 12)
        # 应去重，只保留一条
        matching = [o for o in overrides if o.get("rejected_advice") == "冲突信号偏弱"]
        self.assertEqual(len(matching), 1)
        # 应保留最后一次的
        self.assertEqual(matching[0]["writer_reason"], "理由4")


class NovelPipelineIntegrationTests(unittest.TestCase):
    """novel_pipeline.py 与各模块集成测试"""

    def test_pipeline_imports_do_not_crash(self):
        """验证 pipeline 导入所有依赖不崩溃"""
        # 临时重定向以避免 mock 警告
        try:
            from novel_pipeline import (
                ch_str, word_count_zh,
                apply_mock_env, has_actionable_audit_issue,
                extract_foreshadow_id,
            )
        except ImportError as e:
            # 部分模块可能需要 mock 环境
            self.skipTest(f"Import skipped due to missing dependency: {e}")

    def test_word_count_zh(self):
        from novel_pipeline import word_count_zh

        self.assertEqual(word_count_zh(""), 0)
        self.assertEqual(word_count_zh("Hello World"), 0)
        self.assertEqual(word_count_zh("你好"), 2)
        self.assertEqual(word_count_zh("你好World"), 2)

    def test_has_actionable_audit_issue(self):
        from novel_pipeline import has_actionable_audit_issue

        self.assertFalse(has_actionable_audit_issue("未发现明显逻辑问题"))
        self.assertFalse(has_actionable_audit_issue("未发现明显问题"))
        self.assertTrue(has_actionable_audit_issue("发现【问题位置】时间线矛盾"))
        self.assertTrue(has_actionable_audit_issue("存在占位符"))

    def test_extract_foreshadow_id(self):
        from novel_pipeline import extract_foreshadow_id

        self.assertEqual(extract_foreshadow_id("F001"), "F001")
        self.assertEqual(extract_foreshadow_id("参考f003号事件"), "F003")
        self.assertIsNone(extract_foreshadow_id("无伏笔"))

    def test_apply_mock_env(self):
        import os
        from novel_pipeline import apply_mock_env

        apply_mock_env(True)
        self.assertEqual(os.environ.get("NOVEL_LLM_MODE"), "mock")
        self.assertEqual(os.environ.get("NOVEL_RAG_MODE"), "mock")

        apply_mock_env(False)
        # False 调用不改变环境

    def test_word_count_with_only_punctuation(self):
        from novel_pipeline import word_count_zh

        self.assertEqual(word_count_zh("。，！？、"), 0)
        self.assertEqual(word_count_zh("「走吧」他说"), 4)  # 走+吧+他+说 = 4 CJK chars
