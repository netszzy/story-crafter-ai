import json
import tempfile
import unittest
from pathlib import Path

from pydantic import ValidationError

import novel_pipeline
from editor_memo import (
    _extract_json_object,
    _fallback_memo,
    _should_mock,
    memo_to_revision_prompt,
    read_memo,
    synthesize_memo,
    write_memo,
)
from novel_schemas import (
    DiagnosticReservation,
    DramaticDiagnostics,
    EditorMemo,
    MemoItem,
    SceneTension,
)


def _sample_diag(chapter_number: int = 1, drama_score: int = 72) -> DramaticDiagnostics:
    return DramaticDiagnostics(
        chapter_number=chapter_number,
        title="测试章",
        model_used="unit-model",
        provider_used="unit",
        pressure_curve_score=70,
        character_arc_score=75,
        cinematic_score=71,
        overall_drama_score=drama_score,
        scenes=[
            SceneTension(
                scene_index=1,
                scene_summary="测试场景",
                must_do="决定是否行动",
                cost_if_fail="失去信任",
                pressure_level=6,
                pressure_clarity=7,
            )
        ],
        top_revision_targets=[
            "场景1：代价还可更具体，补一句拒绝后的损失。",
            "对白工具化：沈逐光的台词缺乏潜台词。",
        ],
        is_mock=False,
    )


def _sample_quality(score: int = 68) -> dict:
    return {
        "score": score,
        "grade": "B",
        "findings": [
            {"level": "warning", "item": "节奏不均", "detail": "中段拖沓，建议缩减过渡段。"},
            {"level": "info", "item": "钩子偏弱", "detail": "章末悬念可更强烈。"},
        ],
    }


# ── Schema tests ──────────────────────────────────────────────────────────────


class MemoSchemaTests(unittest.TestCase):
    def test_memo_item_defaults(self) -> None:
        item = MemoItem()
        self.assertEqual(item.priority, "P1")
        self.assertEqual(item.source, "")
        self.assertEqual(item.location, "")

    def test_memo_item_invalid_priority(self) -> None:
        with self.assertRaises(ValidationError):
            MemoItem(priority="P3")

    def test_editor_memo_defaults(self) -> None:
        memo = EditorMemo(chapter_number=1)
        self.assertEqual(memo.chapter_number, 1)
        self.assertEqual(memo.top_3_must_fix, [])
        self.assertEqual(memo.contradictions, [])
        self.assertEqual(memo.score_summary, {})
        self.assertFalse(memo.ready_to_finalize)
        self.assertFalse(memo.is_mock)

    def test_editor_memo_json_roundtrip(self) -> None:
        memo = EditorMemo(
            chapter_number=3,
            title="测试",
            model_used="deepseek-v4",
            provider_used="deepseek",
            top_3_must_fix=[
                MemoItem(
                    priority="P0",
                    source="audit",
                    location="第3段",
                    issue="逻辑断裂",
                    action="补充过渡句",
                    acceptance="读者能理解因果关系",
                ),
                MemoItem(
                    priority="P1",
                    source="drama",
                    location="场景2",
                    issue="压力不可见",
                    action="加入身体反应",
                    acceptance="读者感受到角色紧张",
                ),
            ],
            contradictions=["质量诊断与戏剧诊断存在分歧"],
            score_summary={"drama": 72, "quality": 68},
            ready_to_finalize=False,
            overall_assessment="有必改项，需要修订。",
            is_mock=False,
        )
        raw = memo.model_dump_json(indent=2)
        restored = EditorMemo.model_validate(json.loads(raw))

        self.assertEqual(restored.chapter_number, 3)
        self.assertEqual(len(restored.top_3_must_fix), 2)
        self.assertEqual(restored.top_3_must_fix[0].priority, "P0")
        self.assertEqual(restored.top_3_must_fix[1].source, "drama")
        self.assertEqual(restored.contradictions[0], "质量诊断与戏剧诊断存在分歧")
        self.assertEqual(restored.score_summary["drama"], 72)
        self.assertFalse(restored.ready_to_finalize)


# ── JSON extraction tests ─────────────────────────────────────────────────────


class ExtractorTests(unittest.TestCase):
    def test_clean_json(self) -> None:
        raw = '{"chapter_number": 1, "top_3_must_fix": []}'
        result = _extract_json_object(raw)
        self.assertEqual(json.loads(result)["chapter_number"], 1)

    def test_markdown_fence(self) -> None:
        raw = '```json\n{"chapter_number": 2}\n```'
        result = _extract_json_object(raw)
        self.assertEqual(json.loads(result)["chapter_number"], 2)

    def test_markdown_fence_no_lang(self) -> None:
        raw = '```\n{"chapter_number": 3}\n```'
        result = _extract_json_object(raw)
        self.assertEqual(json.loads(result)["chapter_number"], 3)

    def test_leading_text(self) -> None:
        raw = '这是分析结果：\n{"chapter_number": 4, "top_3_must_fix": []}'
        result = _extract_json_object(raw)
        self.assertEqual(json.loads(result)["chapter_number"], 4)

    def test_trailing_text(self) -> None:
        raw = '{"chapter_number": 5}\n以上是备忘录。'
        result = _extract_json_object(raw)
        self.assertEqual(json.loads(result)["chapter_number"], 5)

    def test_no_json_raises(self) -> None:
        with self.assertRaises(ValueError):
            _extract_json_object("没有 JSON 对象")

    def test_empty_string_raises(self) -> None:
        with self.assertRaises(ValueError):
            _extract_json_object("")


# ── Fallback memo tests ───────────────────────────────────────────────────────


class FallbackMemoTests(unittest.TestCase):
    def test_empty_inputs_produces_valid_memo(self) -> None:
        memo = _fallback_memo(1)
        self.assertEqual(memo.chapter_number, 1)
        self.assertTrue(memo.is_mock)
        self.assertEqual(memo.model_used, "mock-editor-memo")
        self.assertEqual(memo.provider_used, "mock")
        # No diagnostics → no P0 items → ready
        self.assertTrue(memo.ready_to_finalize)
        self.assertEqual(memo.top_3_must_fix, [])
        self.assertTrue(memo.overall_assessment.startswith("[Mock]"))

    def test_drama_only_populates_items(self) -> None:
        diag = _sample_diag(drama_score=65)
        memo = _fallback_memo(1, drama_diag=diag)

        self.assertEqual(memo.score_summary["drama"], 65)
        self.assertTrue(any(i.source == "drama" for i in memo.top_3_must_fix))
        self.assertTrue(memo.ready_to_finalize)  # P1 items only

    def test_quality_only_populates_items(self) -> None:
        qr = _sample_quality(55)
        memo = _fallback_memo(1, quality_report=qr)

        self.assertEqual(memo.score_summary["quality"], 55)
        self.assertTrue(any(i.source == "quality" for i in memo.top_3_must_fix))

    def test_quality_error_becomes_p0(self) -> None:
        qr = {
            "score": 50,
            "grade": "C",
            "findings": [
                {"level": "error", "item": "逻辑断裂", "detail": "第3段因果关系不成立。"},
            ],
        }
        memo = _fallback_memo(1, quality_report=qr)

        p0_items = [i for i in memo.top_3_must_fix if i.priority == "P0"]
        self.assertEqual(len(p0_items), 1)
        self.assertEqual(p0_items[0].issue, "逻辑断裂")
        self.assertFalse(memo.ready_to_finalize)

    def test_audit_text_triggers_p0(self) -> None:
        audit = "## 审计\n\n【问题位置】第5段\n\n时间线矛盾：上一章是晚上，本章变成上午。"
        memo = _fallback_memo(1, audit_text=audit)

        p0_items = [i for i in memo.top_3_must_fix if i.priority == "P0"]
        self.assertTrue(len(p0_items) >= 1)
        self.assertFalse(memo.ready_to_finalize)

    def test_audit_text_without_bracket_ignored(self) -> None:
        memo = _fallback_memo(1, audit_text="审计未发现问题。")
        self.assertTrue(memo.ready_to_finalize)

    def test_deduplication_by_issue_prefix(self) -> None:
        # Same prefix (60 chars) → dedup by issue[:60]
        prefix = "场景1代价不具体需补损失" * 6  # 72 chars, first 60 identical
        diag = _sample_diag()
        diag.top_revision_targets = [
            prefix + "——A版",
            prefix + "——B版（补充说明）",
        ]
        memo = _fallback_memo(1, drama_diag=diag)

        self.assertLessEqual(len(memo.top_3_must_fix), 1)

    def test_contradiction_drama_high_quality_low(self) -> None:
        diag = _sample_diag(drama_score=80)
        qr = _sample_quality(45)
        memo = _fallback_memo(1, drama_diag=diag, quality_report=qr)

        self.assertTrue(any("戏剧诊断给分较高" in c for c in memo.contradictions))

    def test_contradiction_quality_high_drama_low(self) -> None:
        diag = _sample_diag(drama_score=45)
        qr = _sample_quality(80)
        memo = _fallback_memo(1, drama_diag=diag, quality_report=qr)

        self.assertTrue(any("质量诊断给分较高" in c for c in memo.contradictions))

    def test_no_contradiction_when_scores_close(self) -> None:
        diag = _sample_diag(drama_score=72)
        qr = _sample_quality(68)
        memo = _fallback_memo(1, drama_diag=diag, quality_report=qr)

        self.assertEqual(memo.contradictions, [])

    def test_no_contradiction_without_both_reports(self) -> None:
        diag = _sample_diag(drama_score=80)
        memo = _fallback_memo(1, drama_diag=diag)
        self.assertEqual(memo.contradictions, [])

        qr = _sample_quality(45)
        memo = _fallback_memo(1, quality_report=qr)
        self.assertEqual(memo.contradictions, [])

    def test_max_3_items(self) -> None:
        diag = _sample_diag()
        diag.top_revision_targets = [f"问题{i}" for i in range(5)]
        qr = {
            "score": 50,
            "findings": [
                {"level": "warning", "item": f"发现{i}", "detail": f"详情{i}"}
                for i in range(5)
            ],
        }
        memo = _fallback_memo(1, drama_diag=diag, quality_report=qr)

        self.assertLessEqual(len(memo.top_3_must_fix), 3)


# ── Revision prompt tests ─────────────────────────────────────────────────────


class RevisionPromptTests(unittest.TestCase):
    def test_empty_memo_returns_placeholder(self) -> None:
        memo = EditorMemo(chapter_number=1)
        prompt = memo_to_revision_prompt(memo)
        self.assertIn("暂无必改项", prompt)

    def test_prompt_includes_all_items(self) -> None:
        memo = EditorMemo(
            chapter_number=1,
            top_3_must_fix=[
                MemoItem(
                    priority="P0",
                    source="audit",
                    location="第3段",
                    issue="逻辑断裂",
                    action="补充过渡句",
                    acceptance="因果关系清晰",
                ),
                MemoItem(
                    priority="P1",
                    source="drama",
                    location="场景2",
                    issue="压力不可见",
                    action="加入身体反应",
                    acceptance="读者感受到紧张",
                ),
            ],
            contradictions=["测试矛盾"],
            score_summary={"drama": 72, "quality": 68},
            overall_assessment="需要修订。",
        )
        prompt = memo_to_revision_prompt(memo)

        self.assertIn("[P0]", prompt)
        self.assertIn("[P1]", prompt)
        self.assertIn("逻辑断裂", prompt)
        self.assertIn("压力不可见", prompt)
        self.assertIn("补充过渡句", prompt)
        self.assertIn("测试矛盾", prompt)
        self.assertIn("戏剧:72", prompt)
        self.assertIn("质量:68", prompt)
        self.assertIn("### 改稿约束", prompt)

    def test_prompt_forbids_writer_reservations(self) -> None:
        memo = EditorMemo(
            chapter_number=1,
            chapter_mode="interior",
            style_profile="wang_xiaobo",
            top_3_must_fix=[
                MemoItem(priority="P1", issue="任务卡对齐不足", action="补核心事件"),
            ],
            reservations=[
                DiagnosticReservation(
                    diagnostic_source="quality",
                    rejected_advice="冲突信号偏弱",
                    writer_reason="本章是克制内省章。",
                )
            ],
        )

        prompt = memo_to_revision_prompt(memo)

        self.assertIn("章节模式：interior", prompt)
        self.assertIn("风格档案：wang_xiaobo", prompt)
        self.assertIn("禁止执行", prompt)
        self.assertIn("冲突信号偏弱", prompt)

    def test_prompt_without_scores_or_contradictions(self) -> None:
        memo = EditorMemo(
            chapter_number=1,
            top_3_must_fix=[
                MemoItem(priority="P0", issue="必须修复", action="修复它"),
            ],
        )
        prompt = memo_to_revision_prompt(memo)
        self.assertIn("必须修复", prompt)
        self.assertNotIn("诊断间矛盾", prompt)
        self.assertNotIn("评分摘要", prompt)


# ── Persistence tests ─────────────────────────────────────────────────────────


class MemoPersistenceTests(unittest.TestCase):
    def test_write_creates_json_and_md(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memo = _fallback_memo(1, drama_diag=_sample_diag())

            md_path, json_path = write_memo(root, memo)
            self.assertTrue(md_path.exists())
            self.assertTrue(json_path.exists())
            self.assertIn("编辑备忘录", md_path.read_text(encoding="utf-8"))

    def test_read_memo_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memo = _fallback_memo(3, drama_diag=_sample_diag(3, 75), quality_report=_sample_quality(60))

            write_memo(root, memo)
            restored = read_memo(root, 3)

            self.assertIsNotNone(restored)
            self.assertEqual(restored.chapter_number, 3)  # type: ignore[union-attr]
            self.assertEqual(restored.score_summary.get("drama"), 75)  # type: ignore[union-attr]

    def test_read_memo_missing_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(read_memo(Path(tmp), 99))

    def test_read_memo_corrupted_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            log_dir = root / "04_审核日志"
            log_dir.mkdir(parents=True)
            (log_dir / "第001章_编辑备忘录.json").write_text("{not json", encoding="utf-8")

            self.assertIsNone(read_memo(root, 1))

    def test_write_memo_renders_markdown_with_items(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memo = EditorMemo(
                chapter_number=5,
                model_used="test-model",
                provider_used="test-provider",
                top_3_must_fix=[
                    MemoItem(
                        priority="P0",
                        source="audit",
                        location="第2段",
                        issue="时间线矛盾",
                        action="统一时间表述",
                        acceptance="时间前后一致",
                    ),
                ],
                contradictions=["诊断矛盾：A与B不一致"],
                score_summary={"drama": 80, "quality": 75},
                ready_to_finalize=False,
                overall_assessment="有P0必改项。",
            )

            md_path, _ = write_memo(root, memo)
            content = md_path.read_text(encoding="utf-8")

            self.assertIn("# 第005章 编辑备忘录", content)
            self.assertIn("test-provider/test-model", content)
            self.assertIn("[P0] 时间线矛盾", content)
            self.assertIn("诊断矛盾：A与B不一致", content)
            self.assertIn("戏剧：80", content)

    def test_write_memo_renders_reservations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memo = EditorMemo(
                chapter_number=6,
                chapter_mode="atmosphere",
                style_profile="yu_hua",
                reservations=[
                    DiagnosticReservation(
                        diagnostic_source="quality",
                        rejected_advice="情绪身体化偏弱",
                        writer_reason="用空床和布鞋承载情绪。",
                    )
                ],
            )

            md_path, _ = write_memo(root, memo)
            content = md_path.read_text(encoding="utf-8")

            self.assertIn("章节模式：atmosphere", content)
            self.assertIn("风格档案：yu_hua", content)
            self.assertIn("作家豁免", content)
            self.assertIn("空床和布鞋", content)


# ── Mock routing tests ────────────────────────────────────────────────────────


class MemoRoutingTests(unittest.TestCase):
    def test_should_mock_no_critic_text(self) -> None:
        class NoCritic:
            pass

        self.assertTrue(_should_mock(NoCritic()))

    def test_should_mock_explicit_mock_mode(self) -> None:
        class MockRouter:
            mode = "mock"

        self.assertTrue(_should_mock(MockRouter()))

    def test_should_mock_explicit_real_mode(self) -> None:
        class RealRouter:
            mode = "real"
            critic_text = lambda self, **kw: None  # noqa: E731
            CRITIC_PROVIDER = "deepseek"

        self.assertFalse(_should_mock(RealRouter()))

    def test_mock_mode_uses_fallback(self) -> None:
        class MockRouter:
            mode = "mock"

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            memo = synthesize_memo(root, 1, "测试正文", llm=MockRouter())

        self.assertTrue(memo.is_mock)

    def test_real_mode_calls_critic_text(self) -> None:
        class CaptureRouter:
            mode = "real"
            CRITIC_PROVIDER = "deepseek"
            DEEPSEEK_MODEL = "deepseek-unit"

            def __init__(self) -> None:
                self.captured = {}

            def critic_text(self, **kwargs):
                self.captured = kwargs
                return json.dumps({
                    "chapter_number": 1,
                    "top_3_must_fix": [
                        {
                            "priority": "P1",
                            "source": "drama",
                            "location": "场景1",
                            "issue": "压力不足",
                            "action": "加入身体反应",
                            "acceptance": "读者感知到紧张",
                        }
                    ],
                    "contradictions": [],
                    "score_summary": {"drama": 70},
                    "ready_to_finalize": True,
                    "overall_assessment": "质量良好。",
                }, ensure_ascii=False)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "prompts").mkdir(parents=True)
            (root / "prompts" / "编辑备忘录.md").write_text(
                "{{ json_schema }}", encoding="utf-8"
            )
            router = CaptureRouter()
            memo = synthesize_memo(
                root, 1, "测试正文",
                drama_diag=_sample_diag(),
                quality_report=_sample_quality(),
                llm=router,
            )

        self.assertFalse(memo.is_mock)
        self.assertEqual(router.captured["workflow"], "editor-memo")
        self.assertEqual(router.captured["role"], "editor-memo")
        self.assertEqual(len(memo.top_3_must_fix), 1)
        self.assertTrue(memo.ready_to_finalize)


# ── Pipeline integration tests ────────────────────────────────────────────────


class MemoPipelineTests(unittest.TestCase):
    def test_full_pipeline_mock_generates_memo_files(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            for d in ["02_正文", "04_审核日志", "01_大纲/章纲",
                       "00_世界观/角色档案", "03_滚动记忆",
                       "00_世界观/总纲", "prompts"]:
                (root / d).mkdir(parents=True)
            (root / "02_正文" / "第001章_草稿.md").write_text(
                "# 第001章：雨夜\n\n郁时谌必须选择是否公开秘密。他推开门，雨声从走廊灌进来。沈逐光站在走廊尽头。",
                encoding="utf-8",
            )
            (root / "01_大纲" / "章纲" / "第001章.md").write_text(
                "# 第001章章纲\n\n核心事件：郁时谌面临选择。\n",
                encoding="utf-8",
            )
            (root / "00_世界观" / "世界观.md").write_text(
                "# 世界观\n\n现代都市。\n", encoding="utf-8"
            )
            (root / "03_滚动记忆" / "最近摘要.md").write_text(
                "# 最近摘要\n\n郁时谌收到了一封匿名信。\n", encoding="utf-8"
            )
            (root / "prompts" / "戏剧诊断.md").write_text(
                "{{ axis_context }}\n{{ json_schema }}", encoding="utf-8"
            )
            (root / "prompts" / "编辑备忘录.md").write_text(
                "{{ json_schema }}", encoding="utf-8"
            )

            old = novel_pipeline.PROJECT_DIR
            novel_pipeline.PROJECT_DIR = root
            try:
                novel_pipeline.run_full(1, mock=True, skip_drama_diagnose=False)
            finally:
                novel_pipeline.PROJECT_DIR = old

            memo_json = root / "04_审核日志" / "第001章_编辑备忘录.json"
            memo_md = root / "04_审核日志" / "第001章_编辑备忘录.md"
            self.assertTrue(memo_json.exists(), f"Expected {memo_json} to exist")
            self.assertTrue(memo_md.exists(), f"Expected {memo_md} to exist")

            data = json.loads(memo_json.read_text(encoding="utf-8"))
            self.assertEqual(data["chapter_number"], 1)
            self.assertTrue(data["is_mock"])

    def test_memo_in_revise_from_feedback(self) -> None:
        """V4.0: revise_from_feedback uses memo, not raw 7-block concatenation."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            for d in ["02_正文", "04_审核日志", "01_大纲/章纲",
                       "00_世界观/角色档案", "03_滚动记忆",
                       "00_世界观/总纲", "prompts"]:
                (root / d).mkdir(parents=True)
            (root / "02_正文" / "第001章_草稿.md").write_text(
                "# 第001章：雨夜\n\n郁时谌把信压在掌心下面。沈逐光说：\"你必须今晚决定。\"",
                encoding="utf-8",
            )
            (root / "01_大纲" / "章纲" / "第001章.md").write_text(
                "# 第001章章纲\n\n核心事件：郁时谌面临选择。\n",
                encoding="utf-8",
            )
            (root / "00_世界观" / "世界观.md").write_text(
                "# 世界观\n\n现代都市。\n", encoding="utf-8"
            )
            (root / "03_滚动记忆" / "最近摘要.md").write_text(
                "# 最近摘要\n\n郁时谌收到了一封匿名信。\n", encoding="utf-8"
            )
            (root / "prompts" / "戏剧诊断.md").write_text(
                "{{ axis_context }}\n{{ json_schema }}", encoding="utf-8"
            )
            (root / "prompts" / "编辑备忘录.md").write_text(
                "{{ json_schema }}", encoding="utf-8"
            )

            old = novel_pipeline.PROJECT_DIR
            novel_pipeline.PROJECT_DIR = root
            try:
                novel_pipeline.run_revise_from_feedback(1, mock=True)
            finally:
                novel_pipeline.PROJECT_DIR = old

            # Should have generated the memo file even in mock+revise path
            memo_json = root / "04_审核日志" / "第001章_编辑备忘录.json"
            self.assertTrue(memo_json.exists())


if __name__ == "__main__":
    unittest.main()
