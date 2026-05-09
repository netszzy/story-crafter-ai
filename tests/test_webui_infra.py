import unittest
import tempfile
from dataclasses import dataclass
from pathlib import Path

from webui_infra.components.keyboard import apply_shortcut_to_state, normalize_shortcut
from webui_infra.components.margin_notes import build_margin_notes
from webui_infra.components.scroll_health import (
    collect_scroll_health,
    score_to_scroll_color,
    weakest_chapter,
)
from webui_infra.background_jobs import start_background_job
from webui_infra.inbox import add_inbox_message, mark_inbox_read, read_inbox, unread_count
from webui_infra.navigation import NAV_ITEMS, direct_page_for, visible_nav_for
from webui_infra.pages.writing import _build_inline_revision_blocks, _compose_inline_revision
from webui_infra.pages.continue_writing import _read_last_writing_state
from webui_infra.state import init_session_state, is_llm_running, reset_chapter_buffers, set_llm_running
from webui import _background_success_title, _summarize_background_result, _widget_key


class WebUIStateTests(unittest.TestCase):
    def test_init_session_state_sets_defaults_without_overwriting(self) -> None:
        state = {"_global_mock": True, "writing_draft_buffer": "用户正在编辑"}

        init_session_state(state, default_mock=False)

        self.assertTrue(state["_global_mock"])
        self.assertEqual(state["writing_draft_buffer"], "用户正在编辑")
        self.assertFalse(state["llm_running"])
        self.assertEqual(state["writing_selected_revision_targets"], [])
        self.assertEqual(state["drama_diagnostics_cache"], {})

    def test_session_defaults_do_not_share_mutable_values(self) -> None:
        first = {}
        second = {}

        init_session_state(first)
        init_session_state(second)
        first["writing_selected_revision_targets"].append("场景1")
        first["drama_diagnostics_cache"][1] = {"score": 80}

        self.assertEqual(second["writing_selected_revision_targets"], [])
        self.assertEqual(second["drama_diagnostics_cache"], {})

    def test_reset_chapter_buffers_clears_editor_state(self) -> None:
        state = {
            "writing_draft_dirty": True,
            "writing_draft_buffer": "旧章节正文",
            "writing_selected_revision_targets": ["场景1"],
        }

        reset_chapter_buffers(state)

        self.assertFalse(state["writing_draft_dirty"])
        self.assertEqual(state["writing_draft_buffer"], "")
        self.assertEqual(state["writing_selected_revision_targets"], [])

    def test_llm_running_helpers_manage_lock_message(self) -> None:
        state = {}

        self.assertFalse(is_llm_running(state))
        set_llm_running(state, True, "正在生成")
        self.assertTrue(is_llm_running(state))
        self.assertEqual(state["llm_lock_message"], "正在生成")
        set_llm_running(state, False)

        self.assertFalse(is_llm_running(state))
        self.assertNotIn("llm_lock_message", state)


class WebUINavigationTests(unittest.TestCase):
    def test_navigation_items_are_v5_top_level_states(self) -> None:
        self.assertEqual(NAV_ITEMS, ["写作", "故事圣经", "规划", "AI任务", "设置"])

    def test_legacy_nav_labels_map_to_v5_sections(self) -> None:
        self.assertEqual(visible_nav_for("✍️ 写作"), "写作")
        self.assertEqual(visible_nav_for("写作"), "写作")
        self.assertEqual(visible_nav_for("今天"), "写作")
        self.assertEqual(visible_nav_for("🧭 中台"), "规划")
        self.assertEqual(visible_nav_for("世界观"), "故事圣经")
        self.assertEqual(visible_nav_for("AI 草案"), "AI任务")
        self.assertEqual(visible_nav_for("📜 日志"), "设置")

    def test_legacy_deep_links_keep_concrete_target(self) -> None:
        self.assertEqual(direct_page_for("写作"), "写作")
        self.assertEqual(direct_page_for("中台"), "中台")
        self.assertEqual(direct_page_for("日志"), "日志")


class WebUIWidgetKeyTests(unittest.TestCase):
    def test_review_widgets_include_render_instance_prefix(self) -> None:
        cache_key = "outline_卷纲_第01卷.md"

        first = _widget_key("volume_tab_ai", "reload_review", "outline", cache_key)
        second = _widget_key("assist_tab_volume_ai", "reload_review", "outline", cache_key)
        editable_first = _widget_key("volume_tab_ai", "editable_review", "outline", cache_key)
        editable_second = _widget_key("assist_tab_volume_ai", "editable_review", "outline", cache_key)

        self.assertNotEqual(first, second)
        self.assertNotEqual(editable_first, editable_second)
        self.assertIn("第01卷", first)


class ContinueWritingTests(unittest.TestCase):
    def test_read_last_writing_state_uses_latest_chapter_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = root / "02_正文"
            body.mkdir(parents=True)
            old = body / "第001章_草稿.md"
            new = body / "第002章_修订稿.md"
            old.write_text("第一章正文。\n\n旧段落。", encoding="utf-8")
            new.write_text("第二章正文。\n\n他把信封翻过来，终于看见背面的日期。", encoding="utf-8")

            state = _read_last_writing_state(root)

            self.assertIsNotNone(state)
            self.assertEqual(state.chapter_number, 2)
            self.assertIn("背面的日期", state.last_paragraph)


class KeyboardShortcutTests(unittest.TestCase):
    def test_normalize_shortcut_accepts_query_param_shapes(self) -> None:
        self.assertEqual(normalize_shortcut(["diagnostics"]), "diagnostics_drawer")
        self.assertEqual(normalize_shortcut("focus"), "focus_mode")
        self.assertEqual(normalize_shortcut("missing"), "")

    def test_apply_shortcut_updates_writing_state(self) -> None:
        state = {"_writing_focus_mode": False}

        action = apply_shortcut_to_state(state, "focus")
        self.assertEqual(action, "focus_mode")
        self.assertTrue(state["_writing_focus_mode"])

        apply_shortcut_to_state(state, "command")
        apply_shortcut_to_state(state, "diagnostics")
        apply_shortcut_to_state(state, "ai")
        apply_shortcut_to_state(state, "save")

        self.assertTrue(state["_writing_command_panel"])
        self.assertTrue(state["_writing_diag_drawer"])
        self.assertTrue(state["_writing_ai_panel"])
        self.assertTrue(state["_writing_save_requested"])


class InlineRevisionTests(unittest.TestCase):
    def test_inline_revision_blocks_can_be_accepted_individually(self) -> None:
        original = "第一段。\n第二段旧。\n第三段。\n"
        revised = "第一段。\n第二段新。\n新增一句。\n第三段。\n"

        blocks = _build_inline_revision_blocks(original, revised)
        changed = [block for block in blocks if block["tag"] != "equal"]

        self.assertEqual(len(changed), 1)
        kept = _compose_inline_revision(blocks, {changed[0]["id"]: "reject"})
        accepted = _compose_inline_revision(blocks, {changed[0]["id"]: "accept"})

        self.assertEqual(kept, original)
        self.assertEqual(accepted, revised)


class BackgroundJobTests(unittest.TestCase):
    def test_background_job_stores_result_for_ui_callback(self) -> None:
        state = {}
        job = start_background_job(state, "测试任务", lambda cancel: "done", eta_seconds=1)
        job.thread.join(timeout=3)

        self.assertIs(state["active_job"], job)
        self.assertEqual(job.status, "done")
        self.assertEqual(job.result, "done")

    def test_background_job_can_notify_worker_thread_success(self) -> None:
        seen = []
        state = {}
        job = start_background_job(
            state,
            "测试任务",
            lambda cancel: "done",
            eta_seconds=1,
            notify_success=lambda result: seen.append(result),
        )
        job.thread.join(timeout=3)

        self.assertEqual(seen, ["done"])

    def test_background_job_title_distinguishes_autopilot_round_from_completion(self) -> None:
        result = {
            "status": "advanced",
            "messages": ["场景 001 候选稿已生成", "下一步：生成缺失场景候选稿"],
            "inbox_title": "第2章 AI 自动推进本轮推进结束",
        }

        self.assertEqual(_background_success_title("第2章 AI 自动推进", result), "第2章 AI 自动推进本轮推进结束")
        self.assertIn("下一步：生成缺失场景候选稿", _summarize_background_result(result))

    def test_background_job_title_keeps_real_completion(self) -> None:
        result = {"status": "complete", "messages": ["本章闭环已完成。"]}

        self.assertEqual(_background_success_title("第2章 AI 自动推进", result), "第2章 AI 自动推进已完成")


class InboxTests(unittest.TestCase):
    def test_inbox_persists_unread_messages_and_marks_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            message = add_inbox_message(root, "任务完成", "已生成草案", level="success")

            self.assertEqual(unread_count(root), 1)
            messages = read_inbox(root)
            self.assertEqual(messages[0]["id"], message["id"])
            self.assertFalse(messages[0]["read"])

            changed = mark_inbox_read(root, {message["id"]})
            self.assertEqual(changed, 1)
            self.assertEqual(unread_count(root), 0)


class MarginNoteTests(unittest.TestCase):
    def test_build_margin_notes_anchors_polish_targets_to_paragraphs(self) -> None:
        text = "第一段开头有雾。\n\n第二段很长，陷入沉默，但这是人物外壳。\n\n最后一段只剩灯。"
        quality = {
            "polish_targets": [
                {
                    "位置": "段落 2",
                    "风险": 6,
                    "问题": "长段落",
                    "原文片段": "第二段很长，陷入沉默",
                    "改法": "拆成两段",
                }
            ],
            "findings": [
                {"level": "warning", "item": "章末余味弱", "detail": "最后一段需要复核"},
                {"level": "accepted_by_writer", "item": "冲突弱", "detail": "已保护"},
            ],
        }

        notes = build_margin_notes(text, quality, limit=5)

        self.assertEqual(notes[0].paragraph_index, 2)
        self.assertEqual(notes[0].title, "长段落")
        self.assertTrue(any(note.paragraph_index == 3 for note in notes))
        self.assertFalse(any(note.title == "冲突弱" for note in notes))


@dataclass
class _Snap:
    chapter_number: int
    overall_drama_score: int
    is_mock: bool = False


@dataclass
class _Trends:
    chapters: list[_Snap]


class ScrollHealthTests(unittest.TestCase):
    def test_score_color_uses_cream_to_brown_scale(self) -> None:
        self.assertEqual(score_to_scroll_color(None), "#ded6c7")
        self.assertNotIn(score_to_scroll_color(90), {"#2ea043", "#d29922", "#9f3737"})
        self.assertNotIn(score_to_scroll_color(40), {"#2ea043", "#d29922", "#9f3737"})

    def test_collect_scroll_health_uses_scores_and_weakest_chapter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "01_大纲" / "章纲").mkdir(parents=True)
            (root / "02_正文").mkdir(parents=True)
            (root / "04_审核日志").mkdir(parents=True)
            (root / "01_大纲" / "章纲" / "第001章.md").write_text("第001章", encoding="utf-8")
            (root / "01_大纲" / "章纲" / "第002章.md").write_text("第002章", encoding="utf-8")
            (root / "02_正文" / "第001章_草稿.md").write_text("第一章。\n\n值得保留的句子。", encoding="utf-8")
            (root / "04_审核日志" / "第002章_质量诊断.json").write_text(
                '{"overall_score": 52, "findings": [{"level": "warning", "item": "章末余味弱"}]}',
                encoding="utf-8",
            )
            (root / "04_审核日志" / "第002章_声音诊断.json").write_text(
                '{"flagged_pairs": [{}, {}]}',
                encoding="utf-8",
            )

            rows = collect_scroll_health(root, trends=_Trends([_Snap(1, 82)]))
            weak = weakest_chapter(rows)

            self.assertEqual(len(rows), 2)
            self.assertEqual(rows[0].source, "戏剧")
            self.assertEqual(rows[1].source, "质量")
            self.assertEqual(weak.chapter_number, 2)
            self.assertEqual(rows[1].score_style, 60)


if __name__ == "__main__":
    unittest.main()
