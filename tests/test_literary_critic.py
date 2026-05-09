import json
import tempfile
import unittest
from pathlib import Path

from editor_memo import _fallback_memo
from literary_critic import analyze_literary_view, read_literary_view, write_literary_view
from novel_schemas import LiteraryView, MemorableMoment
from style_court import adjudicate, read_style_court, write_style_court


class MockRouter:
    mode = "mock"


def _atmosphere_quality() -> dict:
    return {
        "score": 59,
        "grade": "C",
        "task_card_alignment": {
            "chapter_mode": "atmosphere",
            "style_profile": "yu_hua",
        },
        "findings": [
            {
                "level": "warning",
                "item": "冲突信号偏弱",
                "detail": "正文缺少可感知的阻力、代价、秘密或选择压力。",
                "finding_key": "conflict-low",
            },
            {
                "level": "info",
                "item": "情绪身体化偏弱",
                "detail": "建议落到呼吸、手、喉咙、停顿或动作迟疑。",
                "finding_key": "body-low",
            },
            {
                "level": "warning",
                "item": "任务卡对齐不足",
                "detail": "核心事件没有在正文中形成可见落点。",
                "finding_key": "task-card-gap",
            },
            {
                "level": "error",
                "item": "触碰任务卡禁止事项",
                "detail": "正文中出现任务卡 forbidden 项。",
                "finding_key": "forbidden-hit",
            },
        ],
    }


class LiteraryCriticTests(unittest.TestCase):
    def test_schema_roundtrip(self) -> None:
        view = LiteraryView(
            chapter_number=1,
            memorable_moments=[
                MemorableMoment(
                    quote="形状像一枚被压扁的眼睛",
                    why_memorable="物件替情绪说话。",
                    fragility="解释太多会变钝。",
                )
            ],
            cannot_be_quantified=True,
        )
        restored = LiteraryView.model_validate(json.loads(view.model_dump_json()))
        self.assertEqual(restored.chapter_number, 1)
        self.assertTrue(restored.cannot_be_quantified)
        self.assertIn("眼睛", restored.memorable_moments[0].quote)

    def test_mock_finds_appendix_b1_moment_and_marks_mock(self) -> None:
        text = (
            "# 第001章\n\n"
            "雨停在凌晨两点。窗缝里还挂着水声，像有人把一串旧钥匙慢慢拖过墙面。\n\n"
            "地板上留下一小摊水，形状像一枚被压扁的眼睛。"
        )
        view = analyze_literary_view(Path("."), 1, text, llm=MockRouter())
        quotes = "\n".join(item.quote for item in view.memorable_moments)

        self.assertTrue(view.is_mock)
        self.assertTrue(view.cannot_be_quantified)
        self.assertIn("被压扁的眼睛", quotes)
        self.assertTrue(any("未调用真实文学批评模型" in item for item in view.reader_residue))

    def test_write_and_read_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            view = analyze_literary_view(root, 2, "他没有说话，只把信封推远了一点。", llm=MockRouter())
            write_literary_view(root, view)
            restored = read_literary_view(root, 2)

            self.assertIsNotNone(restored)
            self.assertEqual(restored.chapter_number, 2)  # type: ignore[union-attr]
            self.assertTrue(restored.is_mock)  # type: ignore[union-attr]

    def test_prompt_contains_non_quantified_json_contract(self) -> None:
        prompt = (Path(__file__).resolve().parents[1] / "prompts" / "文学批评.md").read_text(encoding="utf-8")
        self.assertIn("不可量化", prompt)
        self.assertIn("只输出 JSON", prompt)
        self.assertIn("文学风险", prompt)


class StyleCourtTests(unittest.TestCase):
    def test_style_court_contests_soft_findings_but_confirms_hard_constraints(self) -> None:
        view = LiteraryView(
            chapter_number=1,
            memorable_moments=[MemorableMoment(quote="被压扁的眼睛")],
            literary_risks=["强行补冲突和身体动作会破坏克制。"],
            cannot_be_quantified=True,
        )
        court = adjudicate(Path("."), 1, _atmosphere_quality(), view)
        contested_text = "\n".join(item.issue for item in court.contested_issues)
        confirmed_text = "\n".join(item.issue for item in court.confirmed_issues)

        self.assertIn("冲突信号偏弱", contested_text)
        self.assertIn("情绪身体化偏弱", contested_text)
        self.assertIn("任务卡对齐不足", confirmed_text)
        self.assertIn("触碰任务卡禁止事项", confirmed_text)
        self.assertTrue(court.literary_priorities)

    def test_style_court_persistence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            view = LiteraryView(chapter_number=3, cannot_be_quantified=True)
            court = adjudicate(root, 3, _atmosphere_quality(), view)
            write_style_court(root, court)
            restored = read_style_court(root, 3)

            self.assertIsNotNone(restored)
            self.assertGreaterEqual(len(restored.contested_issues), 1)  # type: ignore[union-attr]

    def test_editor_memo_fallback_keeps_contested_out_of_must_fix(self) -> None:
        view = LiteraryView(
            chapter_number=1,
            memorable_moments=[MemorableMoment(quote="被压扁的眼睛")],
            literary_risks=["强行补冲突和身体动作会破坏克制。"],
            cannot_be_quantified=True,
        )
        court = adjudicate(Path("."), 1, _atmosphere_quality(), view)
        memo = _fallback_memo(
            1,
            quality_report=_atmosphere_quality(),
            literary_view=view,
            style_court_decision=court,
        )
        must_fix = "\n".join(item.issue for item in memo.top_3_must_fix)
        reservations = "\n".join(item.rejected_advice for item in memo.reservations)

        self.assertNotIn("冲突信号偏弱", must_fix)
        self.assertNotIn("情绪身体化偏弱", must_fix)
        self.assertIn("任务卡对齐不足", must_fix)
        self.assertIn("触碰任务卡禁止事项", must_fix)
        self.assertIn("冲突信号偏弱", reservations)


if __name__ == "__main__":
    unittest.main()
