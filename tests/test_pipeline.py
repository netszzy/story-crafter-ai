from __future__ import annotations

import gc
import hashlib
import json
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace

import novel_pipeline
import planning_assist
import webui
from novel_schemas import ChapterTaskCard
from book_manager import (
    create_book,
    get_active_book,
    ensure_book_registry,
    import_book,
    list_books,
    remove_book,
    rename_book,
    set_active_book,
)
from chapter_ops import collect_chapter_artifacts, delete_chapter_to_recycle
from cost_tracker import build_usage_summary, estimate_cost, estimate_tokens, estimate_cost_usd, usage_from_provider
from llm_router import LLMRouter
from long_structure import (
    active_volume_for_chapter,
    ensure_default_volumes,
    list_volume_plans,
    volume_axis_block,
)
from onboarding import (
    adopt_ai_draft,
    build_story_spec_from_preset,
    delete_ai_draft,
    generate_startup_package,
    infer_adoption_target,
    list_ai_drafts,
    placeholder_fix_suggestions,
)
from project_archive import collect_version_backups, create_project_snapshot, restore_version_backup
from planning_assist import (
    compact_planning_text,
    generate_character_batch_drafts,
    generate_chapter_outline_draft,
    generate_character_draft,
    generate_outline_draft,
    generate_volume_outline_draft,
    generate_worldbuilding_draft,
    split_character_batch,
)
from project_center import (
    CLARIFY,
    QUALITY,
    SPEC,
    TASKS,
    build_project_status,
    collect_character_roster_issues,
    collect_linkage_drift_issues,
    collect_story_consistency_warnings,
    ensure_project_center,
    generate_quality_report,
    generate_writing_tasks,
    run_v1_upgrade,
)
from quality_diagnostics import (
    analyze_chapter_quality,
    apply_writer_overrides,
    build_polish_targets,
    build_revision_checklist,
    checklist_to_assist_request,
    quality_needs_revision,
    polish_targets_to_assist_request,
    read_writer_overrides,
    render_quality_markdown,
    render_revision_brief,
    write_writer_override,
    write_quality_diagnostics,
)
from structured_store import (
    confirm_task_card,
    read_character_states,
    list_scene_drafts,
    next_scene_draft_version,
    parse_chapter_outline,
    parse_foreshadow_table,
    parse_review_report,
    read_task_card,
    read_scene_plan,
    select_scene_draft,
    sync_task_card_from_outline,
    sync_scene_plan_from_task_card,
    update_scene_status,
    update_character_states_with_llm,
    write_memory_json,
    write_review_json_for_source,
)
from workflow_advisor import chapter_flow, onboarding_state, workspace_dashboard


class PipelineHelperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.old_project_dir = novel_pipeline.PROJECT_DIR
        novel_pipeline.PROJECT_DIR = self.root
        (self.root / "03_滚动记忆").mkdir(parents=True)

    def tearDown(self) -> None:
        novel_pipeline.PROJECT_DIR = self.old_project_dir
        self.tmp.cleanup()

    def test_recent_summary_keeps_latest_three_chapters(self) -> None:
        for num in range(1, 5):
            novel_pipeline.update_recent_summary(num, f"第{num}章摘要")

        content = (self.root / "03_滚动记忆" / "最近摘要.md").read_text(encoding="utf-8")
        self.assertNotIn("## 第1章", content)
        self.assertIn("## 第2章", content)
        self.assertIn("## 第3章", content)
        self.assertIn("## 第4章", content)

    def test_foreshadow_table_adds_new_item_and_resolves_existing(self) -> None:
        path = self.root / "03_滚动记忆" / "伏笔追踪.md"
        path.write_text(novel_pipeline.default_foreshadow_table(), encoding="utf-8")
        outline = "- 埋下：【F001】旧照片日期异常\n- 收回：【F001】照片来自父亲留下的暗线"

        novel_pipeline.update_foreshadow_table(1, outline)

        content = path.read_text(encoding="utf-8")
        self.assertIn("F001", content)
        self.assertIn("🟢已回收", content)

    def test_foreshadow_table_upgrades_legacy_columns(self) -> None:
        path = self.root / "03_滚动记忆" / "伏笔追踪.md"
        path.write_text(
            "# 伏笔追踪表\n\n"
            "| 编号 | 埋入章节 | 伏笔内容 | 状态 | 计划回收章节 |\n"
            "|------|---------|---------|------|------------|\n",
            encoding="utf-8",
        )

        novel_pipeline.update_foreshadow_table(2, "- 埋下：钥匙齿痕异常")

        content = path.read_text(encoding="utf-8")
        self.assertIn("| 来源 | 备注 |", content)
        self.assertIn("V1.6 自动登记", content)
        self.assertEqual(parse_foreshadow_table(content)[0].status, "pending")

    def test_scene_review_uses_project_axis_and_writes_json(self) -> None:
        for rel in ["02_正文/第001章_scenes", "03_滚动记忆", "04_审核日志", "05_项目管理", "00_世界观"]:
            (self.root / rel).mkdir(parents=True, exist_ok=True)
        (self.root / "02_正文" / "第001章_scenes" / "scene_001_draft_v001.md").write_text(
            "郁时谌拿到来自未来的礼物。", encoding="utf-8"
        )
        (self.root / "03_滚动记忆" / "最近摘要.md").write_text("## 第1章\n未来礼物出现。", encoding="utf-8")
        (self.root / "00_世界观" / "世界观.md").write_text("# 世界观\n未来礼物有代价。", encoding="utf-8")
        (self.root / "05_项目管理" / "故事规格.md").write_text(
            "# 故事规格\n\n## 1. 一句话概括\n\n**回答**：郁时谌收到来自未来的礼物。\n",
            encoding="utf-8",
        )

        novel_pipeline.run_scene_review(1, 1, mock=True)

        self.assertTrue((self.root / "04_审核日志" / "第001章_scene_001_review.md").exists())
        self.assertTrue((self.root / "04_审核日志" / "第001章_scene_001_review.json").exists())

    def test_save_archives_existing_file(self) -> None:
        novel_pipeline.save("02_正文/第001章_草稿.md", "旧稿", preserve_existing=False)
        novel_pipeline.save("02_正文/第001章_草稿.md", "新稿", preserve_existing=True)

        current = (self.root / "02_正文" / "第001章_草稿.md").read_text(encoding="utf-8")
        versions = list((self.root / "02_正文" / "versions").glob("第001章_草稿_*.md"))
        self.assertEqual(current, "新稿")
        self.assertEqual(len(versions), 1)

    def test_draft_summary_does_not_touch_rolling_memory(self) -> None:
        recent = self.root / "03_滚动记忆" / "最近摘要.md"
        recent.write_text("# 最近章节摘要\n\n旧内容\n", encoding="utf-8")

        md_path, json_path = novel_pipeline.write_draft_summary(1, "临时摘要", "02_正文/第001章_修订稿.md")

        self.assertTrue(md_path.exists())
        self.assertTrue(json_path.exists())
        self.assertEqual(recent.read_text(encoding="utf-8"), "# 最近章节摘要\n\n旧内容\n")
        data = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertEqual(data["status"], "draft_only")

    def test_finalize_source_skips_empty_final_file(self) -> None:
        (self.root / "02_正文").mkdir(parents=True, exist_ok=True)
        (self.root / "02_正文" / "第001章_定稿.md").write_text("", encoding="utf-8")
        (self.root / "02_正文" / "第001章_修订稿.md").write_text("修订稿正文", encoding="utf-8")

        source = novel_pipeline.choose_finalize_source("001")

        self.assertEqual(source, "02_正文/第001章_修订稿.md")

    def test_full_pipeline_uses_revise_route_and_skips_draft_rag(self) -> None:
        for rel in [
            "00_世界观",
            "01_大纲/章纲",
            "02_正文",
            "03_滚动记忆",
            "04_审核日志",
            "05_项目管理",
        ]:
            (self.root / rel).mkdir(parents=True, exist_ok=True)
        (self.root / "01_大纲" / "章纲" / "第001章.md").write_text(
            "# 第001章：测试\n\n## 核心事件\n郁时谌收到礼物。\n\n## 章末悬念\n门外有人敲门。",
            encoding="utf-8",
        )
        (self.root / "03_滚动记忆" / "最近摘要.md").write_text("# 最近章节摘要\n", encoding="utf-8")

        import llm_router
        import rag_engine

        old_router = llm_router.LLMRouter
        old_rag = rag_engine.NovelRAG

        class FakeRouter:
            revise_calls = 0

            DEEPSEEK_MODEL = "fake-critic"

            def __init__(self, *args, **kwargs):
                pass

            def assist_text(self, *args, **kwargs):
                return '{"planted": [], "resolved": []}'

            def generate_chapter(self, *args, **kwargs):
                return "# 第001章：测试\n\n郁时谌把礼物放在桌上。门外有人敲门？"

            def audit_logic(self, *args, **kwargs):
                return "【问题位置】需要强化章末钩子。"

            def check_ai_flavor_local(self, *args, **kwargs):
                return "未发现明显 AI 味。"

            def reader_mirror(self, *args, **kwargs):
                return "追看点需要强化。"

            def deep_check(self, *args, **kwargs):
                return "情感冲击偏弱。"

            def revise_chapter(self, *args, **kwargs):
                type(self).revise_calls += 1
                return "# 第001章：测试\n\n郁时谌把礼物放在桌上。门外第二次敲门：谁知道这个保管箱？"

            def summarize_local(self, *args, **kwargs):
                return "草稿阶段临时摘要。"

        class FakeRAG:
            index_calls = 0

            def __init__(self, *args, **kwargs):
                pass

            def build_context(self, *args, **kwargs):
                return ""

            def index_chapter(self, *args, **kwargs):
                type(self).index_calls += 1

        try:
            llm_router.LLMRouter = FakeRouter
            rag_engine.NovelRAG = FakeRAG
            novel_pipeline.run_full(1, mock=True)
        finally:
            llm_router.LLMRouter = old_router
            rag_engine.NovelRAG = old_rag

        self.assertEqual(FakeRouter.revise_calls, 1)
        self.assertEqual(FakeRAG.index_calls, 0)
        self.assertTrue((self.root / "04_审核日志" / "第001章_草稿摘要.md").exists())
        # 戏剧诊断对默认 plot 模式必跑；只有 interior / atmosphere / bridge 模式才跳过。
        self.assertTrue((self.root / "04_审核日志" / "第001章_戏剧诊断.json").exists())
        # 文学批评和风格法庭无 mode 限制，必跑。
        self.assertTrue((self.root / "04_审核日志" / "第001章_文学批评.json").exists())
        self.assertTrue((self.root / "04_审核日志" / "第001章_风格法庭.json").exists())
        self.assertNotIn("auto-chapter-001", (self.root / "03_滚动记忆" / "最近摘要.md").read_text(encoding="utf-8"))

    def test_revise_from_feedback_prioritizes_dramatic_diagnostics(self) -> None:
        for rel in [
            "00_世界观",
            "01_大纲/章纲",
            "02_正文",
            "03_滚动记忆",
            "04_审核日志",
            "05_项目管理",
        ]:
            (self.root / rel).mkdir(parents=True, exist_ok=True)
        (self.root / "01_大纲" / "章纲" / "第001章.md").write_text("# 第001章：测试", encoding="utf-8")
        (self.root / "02_正文" / "第001章_草稿.md").write_text("郁时谌必须选择是否公开秘密。", encoding="utf-8")
        (self.root / "04_审核日志" / "第001章_戏剧诊断.json").write_text(
            json.dumps(
                {
                    "chapter_number": 1,
                    "pressure_curve_score": 40,
                    "character_arc_score": 50,
                    "cinematic_score": 60,
                    "overall_drama_score": 50,
                    "top_revision_targets": ["场景1：压力不可见，补出拒绝后的具体损失。"],
                    "is_mock": False,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        import llm_router
        import rag_engine

        old_router = llm_router.LLMRouter
        old_rag = rag_engine.NovelRAG

        class FakeRouter:
            user_prompt = ""
            DEEPSEEK_MODEL = "fake-critic"

            def __init__(self, *args, **kwargs):
                pass

            def revise_chapter(self, system_prompt, ctx, prompt, task_card_text=""):
                type(self).user_prompt = prompt
                return "修订后正文"

            def audit_logic(self, *args, **kwargs):
                return "复审通过"

        class FakeRAG:
            def __init__(self, *args, **kwargs):
                pass

            def build_context(self, *args, **kwargs):
                return ""

        try:
            llm_router.LLMRouter = FakeRouter
            rag_engine.NovelRAG = FakeRAG
            novel_pipeline.run_revise_from_feedback(1, mock=True)
        finally:
            llm_router.LLMRouter = old_router
            rag_engine.NovelRAG = old_rag

        # V4.0: revise prompt uses synthesized editor memo, not raw 7-block concat
        self.assertIn("编辑备忘录", FakeRouter.user_prompt)
        self.assertIn("压力不可见", FakeRouter.user_prompt)
        # Memo items should be in the prompt with priority markers
        self.assertIn("[P1]", FakeRouter.user_prompt)


class ChapterOpsTests(unittest.TestCase):
    def test_delete_chapter_moves_all_artifacts_to_recycle_bin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel in [
                "01_大纲/章纲/第001章_scenes",
                "02_正文/第001章_scenes",
                "03_滚动记忆/章节记忆",
                "04_审核日志",
                "02_正文/versions",
                "04_审核日志/versions",
            ]:
                (root / rel).mkdir(parents=True, exist_ok=True)
            files = [
                "01_大纲/章纲/第001章.md",
                "01_大纲/章纲/第001章_task_card.json",
                "01_大纲/章纲/第001章_scenes/scene_plan.json",
                "02_正文/第001章_草稿.md",
                "02_正文/第001章_scenes/scene_001_draft_v001.md",
                "03_滚动记忆/章节记忆/第001章_memory.json",
                "04_审核日志/第001章_审计.md",
                "04_审核日志/第001章_AI味检查.md",
                "02_正文/versions/第001章_草稿_20260101.md",
            ]
            for rel in files:
                (root / rel).write_text("x", encoding="utf-8")

            artifacts = collect_chapter_artifacts(root, 1)
            result = delete_chapter_to_recycle(root, 1, reason="测试清理")

            self.assertEqual(len(artifacts), len(result["deleted"]))
            self.assertFalse((root / "01_大纲" / "章纲" / "第001章.md").exists())
            recycle_dir = root / result["recycle_dir"]
            self.assertTrue((recycle_dir / "delete_manifest.md").exists())
            self.assertTrue((recycle_dir / "02_正文" / "第001章_草稿.md").exists())


class ProjectArchiveTests(unittest.TestCase):
    def test_snapshot_excludes_secrets_logs_and_versions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for rel in ["00_世界观", "02_正文/versions", "logs"]:
                (root / rel).mkdir(parents=True, exist_ok=True)
            (root / ".env").write_text("ANTHROPIC_API_KEY=secret", encoding="utf-8")
            (root / "00_世界观" / "世界观.md").write_text("世界", encoding="utf-8")
            (root / "02_正文" / "versions" / "第001章_草稿_20260101_010101.md").write_text("旧稿", encoding="utf-8")
            (root / "logs" / "llm_calls.jsonl").write_text("{}", encoding="utf-8")

            result = create_project_snapshot(root, label="验收")

            self.assertTrue(result.path.exists())
            with zipfile.ZipFile(result.path) as zf:
                names = set(zf.namelist())
            self.assertIn("snapshot_manifest.json", names)
            self.assertIn("00_世界观/世界观.md", names)
            self.assertNotIn(".env", names)
            self.assertNotIn("logs/llm_calls.jsonl", names)
            self.assertNotIn("02_正文/versions/第001章_草稿_20260101_010101.md", names)

    def test_restore_version_backup_preserves_current_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            version_dir = root / "00_世界观" / "versions"
            version_dir.mkdir(parents=True, exist_ok=True)
            current = root / "00_世界观" / "世界观.md"
            current.write_text("当前", encoding="utf-8")
            backup = version_dir / "世界观_20260101_010101.md"
            backup.write_text("旧版", encoding="utf-8")

            rows = collect_version_backups(root)
            result = restore_version_backup(root, "00_世界观/versions/世界观_20260101_010101.md")

            self.assertEqual(rows[0]["target_rel_path"].replace("\\", "/"), "00_世界观/世界观.md")
            self.assertEqual(current.read_text(encoding="utf-8"), "旧版")
            self.assertTrue((root / result["current_backup"]).exists())
            self.assertIn("pre_restore", result["current_backup"])


class LLMRouterTests(unittest.TestCase):
    def test_mock_mode_writes_hashed_log_without_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            router = LLMRouter(mode="mock", project_dir=tmp)
            text = router.generate_chapter("系统提示", "上下文", "# 第001章：测试")
            self.assertIn("第001章", text)
            self.assertIn("Mock 模式", text)
            self.assertIn("未做文学质量评估", text)

            log_path = Path(tmp) / "logs" / "llm_calls.jsonl"
            log = log_path.read_text(encoding="utf-8")
            self.assertIn('"input_hash"', log)
            self.assertNotIn("系统提示", log)
            self.assertNotIn("上下文", log)

    def test_mock_audit_declares_no_literary_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            router = LLMRouter(mode="mock", project_dir=tmp)
            text = router.audit_logic("他收到信。", "世界观", "")

            self.assertIn("Mock 模式", text)
            self.assertIn("未做文学质量评估", text)

    def test_runtime_parameters_are_loaded_from_env(self) -> None:
        old_values = {key: os.environ.get(key) for key in [
            "NOVEL_CLAUDE_MAX_TOKENS",
            "NOVEL_CLAUDE_TEMPERATURE",
            "NOVEL_OLLAMA_NUM_PREDICT",
            "NOVEL_OLLAMA_TOP_P",
            "NOVEL_PROSE_PROVIDER",
            "NOVEL_CRITIC_PROVIDER",
            "NOVEL_OPENROUTER_PROSE_MODEL",
            "NOVEL_CUSTOM_BASE_URL",
            "NOVEL_CUSTOM_MODEL",
            "NOVEL_CUSTOM_PROSE_MODEL",
            "NOVEL_OPENAI_TIMEOUT_SECONDS",
        ]}
        try:
            os.environ["NOVEL_CLAUDE_MAX_TOKENS"] = "12345"
            os.environ["NOVEL_CLAUDE_TEMPERATURE"] = "0.55"
            os.environ["NOVEL_OLLAMA_NUM_PREDICT"] = "321"
            os.environ["NOVEL_OLLAMA_TOP_P"] = "0.75"
            os.environ["NOVEL_PROSE_PROVIDER"] = "openrouter"
            os.environ["NOVEL_CRITIC_PROVIDER"] = "openrouter"
            os.environ["NOVEL_OPENROUTER_PROSE_MODEL"] = "openrouter/auto"
            os.environ["NOVEL_CUSTOM_BASE_URL"] = "https://api.example.com/v1"
            os.environ["NOVEL_CUSTOM_MODEL"] = "example-default"
            os.environ["NOVEL_CUSTOM_PROSE_MODEL"] = "example-prose"
            os.environ["NOVEL_OPENAI_TIMEOUT_SECONDS"] = "456"
            router = LLMRouter(mode="mock", project_dir=tempfile.gettempdir())

            self.assertEqual(router.CLAUDE_MAX_TOKENS, 12345)
            self.assertEqual(router.CLAUDE_TEMPERATURE, 0.55)
            self.assertEqual(router.OLLAMA_NUM_PREDICT, 321)
            self.assertEqual(router.OLLAMA_TOP_P, 0.75)
            self.assertEqual(router.PROSE_PROVIDER, "openrouter")
            self.assertEqual(router.CRITIC_PROVIDER, "openrouter")
            self.assertEqual(router.OPENROUTER_PROSE_MODEL, "openrouter/auto")
            self.assertEqual(router.CUSTOM_BASE_URL, "https://api.example.com/v1")
            self.assertEqual(router.CUSTOM_MODEL, "example-default")
            self.assertEqual(router.CUSTOM_PROSE_MODEL, "example-prose")
            self.assertEqual(router.OPENAI_TIMEOUT_SECONDS, 456)
        finally:
            for key, value in old_values.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_openrouter_provider_falls_back_to_mock_without_key_in_auto_mode(self) -> None:
        old_provider = os.environ.get("NOVEL_PROSE_PROVIDER")
        old_key = os.environ.get("OPENROUTER_API_KEY")
        try:
            os.environ["NOVEL_PROSE_PROVIDER"] = "openrouter"
            os.environ.pop("OPENROUTER_API_KEY", None)
            router = LLMRouter(mode="auto", project_dir=tempfile.mkdtemp())
            text = router.generate_chapter("系统", "上下文", "# 第001章：测试")
            self.assertIn("第001章", text)
        finally:
            if old_provider is None:
                os.environ.pop("NOVEL_PROSE_PROVIDER", None)
            else:
                os.environ["NOVEL_PROSE_PROVIDER"] = old_provider
            if old_key is None:
                os.environ.pop("OPENROUTER_API_KEY", None)
            else:
                os.environ["OPENROUTER_API_KEY"] = old_key

    def test_custom_provider_falls_back_to_mock_without_key_in_auto_mode(self) -> None:
        old_values = {key: os.environ.get(key) for key in [
            "NOVEL_PROSE_PROVIDER",
            "NOVEL_CUSTOM_API_KEY",
            "NOVEL_CUSTOM_BASE_URL",
            "NOVEL_CUSTOM_PROSE_MODEL",
        ]}
        try:
            os.environ["NOVEL_PROSE_PROVIDER"] = "custom"
            os.environ.pop("NOVEL_CUSTOM_API_KEY", None)
            os.environ["NOVEL_CUSTOM_BASE_URL"] = "https://api.example.com/v1"
            os.environ["NOVEL_CUSTOM_PROSE_MODEL"] = "example-model"
            router = LLMRouter(mode="auto", project_dir=tempfile.mkdtemp())
            text = router.generate_chapter("系统", "上下文", "# 第001章：测试")
            self.assertIn("第001章", text)
            self.assertIn("Mock 模式", text)
        finally:
            for key, value in old_values.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

    def test_custom_chat_response_text_accepts_string_and_dict(self) -> None:
        router = LLMRouter(mode="mock", project_dir=tempfile.gettempdir())

        self.assertEqual(router._chat_response_text("直接文本"), "直接文本")
        self.assertEqual(
            router._chat_response_text({"choices": [{"message": {"content": "字典文本"}}]}),
            "字典文本",
        )
        self.assertEqual(
            router._chat_response_text({"choices": [{"text": "旧式文本"}]}),
            "旧式文本",
        )

    def test_custom_chat_rejects_html_page_response(self) -> None:
        router = LLMRouter(mode="mock", project_dir=tempfile.gettempdir())

        with self.assertRaisesRegex(RuntimeError, "返回了网页 HTML"):
            router._validate_chat_text(
                '<!DOCTYPE html><html><head><title>AI聊天</title></head><body></body></html>',
                provider="通用接口",
            )

    def test_custom_timeout_error_gets_actionable_message(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            router = LLMRouter(mode="mock", project_dir=tmp)
            router.CUSTOM_PROVIDER_NAME = "通用接口"
            router.OPENAI_TIMEOUT_SECONDS = 120

            class FakeCompletions:
                def create(self, **kwargs):
                    raise TimeoutError("Request timed out.")

            class FakeChat:
                completions = FakeCompletions()

            class FakeClient:
                chat = FakeChat()

            router._get_custom_client = lambda: FakeClient()  # type: ignore[method-assign]

            with self.assertRaisesRegex(RuntimeError, "NOVEL_OPENAI_TIMEOUT_SECONDS"):
                router._custom_chat(
                    "assist_volume_outline",
                    "director",
                    "example-model",
                    [{"role": "user", "content": "生成卷纲"}],
                    "payload",
                    max_tokens=8000,
                    temperature=0.4,
                )

    def test_custom_chat_retries_gateway_timeout_with_compacted_payload(self) -> None:
        router = LLMRouter(mode="mock", project_dir=tempfile.gettempdir())
        router.CUSTOM_RETRY_INPUT_CHAR_LIMIT = 1000
        router.CUSTOM_RETRY_MAX_TOKENS = 2000
        calls = []

        class FakeCompletions:
            def create(self, **kwargs):
                calls.append(kwargs)
                if len(calls) == 1:
                    raise RuntimeError("Error code: 524 - origin_response_timeout")
                return {"choices": [{"message": {"content": "压缩后成功"}}]}

        class FakeChat:
            completions = FakeCompletions()

        class FakeClient:
            chat = FakeChat()

        router._get_custom_client = lambda: FakeClient()  # type: ignore[method-assign]
        text = router._custom_chat(
            "generate_chapter",
            "prose_writer",
            "custom-model",
            [{"role": "system", "content": "系统"}, {"role": "user", "content": "长上下文" * 1000}],
            "payload",
            max_tokens=8000,
            temperature=0.5,
        )

        self.assertEqual(text, "压缩后成功")
        self.assertEqual(len(calls), 2)
        self.assertLessEqual(calls[1]["max_tokens"], 2000)
        self.assertIn("已自动压缩", calls[1]["messages"][-1]["content"])

    def test_custom_blocked_error_gets_actionable_message_after_retry(self) -> None:
        router = LLMRouter(mode="mock", project_dir=tempfile.gettempdir())
        router.CUSTOM_PROVIDER_NAME = "通用接口"
        router.CUSTOM_RETRY_INPUT_CHAR_LIMIT = 1000

        class FakeCompletions:
            def create(self, **kwargs):
                raise RuntimeError("Your request was blocked.")

        class FakeChat:
            completions = FakeCompletions()

        class FakeClient:
            chat = FakeChat()

        router._get_custom_client = lambda: FakeClient()  # type: ignore[method-assign]

        with self.assertRaisesRegex(RuntimeError, "拦截了正式创作请求"):
            router._custom_chat(
                "generate_chapter",
                "prose_writer",
                "custom-model",
                [{"role": "user", "content": "长上下文" * 1000}],
                "payload",
                max_tokens=8000,
                temperature=0.5,
            )

    def test_ai_flavor_mock_reads_project_axis_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "00_世界观").mkdir(parents=True)
            (root / "05_项目管理").mkdir(parents=True)
            (root / "00_世界观" / "文风档案.md").write_text("# 文风档案\n- 避免空泛抒情。", encoding="utf-8")
            (root / "05_项目管理" / "故事规格.md").write_text(
                "# 故事规格\n\n## 1. 一句话概括\n\n**回答**：郁时谌收到来自未来的礼物。\n",
                encoding="utf-8",
            )

            result = LLMRouter(mode="mock", project_dir=root).check_ai_flavor_local("郁时谌关掉电脑。")

            self.assertIn("项目文风", result)
            self.assertIn("故事规格", result)

    def test_mock_llm_log_records_token_usage_and_cost_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            router = LLMRouter(mode="mock", project_dir=root)

            router.assist_text("系统", "请生成角色档案", workflow="assist_character", role="director")

            records = (root / "logs" / "llm_calls.jsonl").read_text(encoding="utf-8").splitlines()
            item = json.loads(records[-1])
            self.assertGreater(item["input_tokens"], 0)
            self.assertGreater(item["output_tokens"], 0)
            self.assertEqual(item["total_tokens"], item["input_tokens"] + item["output_tokens"])
            self.assertIn("estimated_cost_usd", item)
            self.assertIn("estimated_cost_currency", item)
            summary = build_usage_summary(root)
            self.assertEqual(summary["totals"]["calls"], 1)
            self.assertGreater(summary["totals"]["total_tokens"], 0)

    def test_anthropic_long_request_uses_streaming(self) -> None:
        class FakeStream:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def until_done(self) -> None:
                pass

            def get_final_message(self):
                return SimpleNamespace(usage={"input_tokens": 10, "output_tokens": 20})

            def get_final_text(self) -> str:
                return "流式完成"

        class FakeMessages:
            def __init__(self):
                self.created = False
                self.streamed = False

            def create(self, **kwargs):
                self.created = True
                raise AssertionError("long Anthropic request should stream")

            def stream(self, **kwargs):
                self.streamed = True
                return FakeStream()

        class FakeRouter(LLMRouter):
            def __init__(self):
                super().__init__(mode="real")
                self.fake_messages = FakeMessages()

            def _get_claude_client(self):
                return SimpleNamespace(messages=self.fake_messages)

        router = FakeRouter()

        text, usage = router._anthropic_message_text("系统", "用户", max_tokens=30000, temperature=0.5)

        self.assertEqual(text, "流式完成")
        self.assertEqual(usage["output_tokens"], 20)
        self.assertTrue(router.fake_messages.streamed)
        self.assertFalse(router.fake_messages.created)


class CostTrackerTests(unittest.TestCase):
    def test_token_estimate_and_cost_estimate_are_deterministic(self) -> None:
        self.assertGreater(estimate_tokens("郁时谌收到来自未来的礼物。"), 0)
        cost = estimate_cost_usd("anthropic", "claude-opus-4-6", 1_000_000, 1_000_000)
        self.assertEqual(cost, 90.0)

    def test_deepseek_official_cny_pricing_uses_cache_split(self) -> None:
        usage = usage_from_provider({
            "prompt_tokens": 1_000_000,
            "completion_tokens": 1_000_000,
            "prompt_cache_hit_tokens": 250_000,
            "prompt_cache_miss_tokens": 750_000,
        })

        cost = estimate_cost(
            "deepseek",
            "deepseek-v4-flash",
            int(usage["input_tokens"]),
            int(usage["output_tokens"]),
            int(usage["input_cache_hit_tokens"]),
            int(usage["input_cache_miss_tokens"]),
        )

        self.assertEqual(cost["currency"], "CNY")
        self.assertEqual(cost["amount"], 2.755)

    def test_usage_summary_reprices_deepseek_logs_as_cny(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "logs").mkdir()
            record = {
                "provider": "deepseek",
                "model": "deepseek-v4-pro",
                "workflow": "audit_logic",
                "input_tokens": 1_000_000,
                "output_tokens": 1_000_000,
                "input_cache_hit_tokens": 100_000,
                "input_cache_miss_tokens": 900_000,
            }
            (root / "logs" / "llm_calls.jsonl").write_text(json.dumps(record, ensure_ascii=False) + "\n", encoding="utf-8")

            summary = build_usage_summary(root)

            self.assertEqual(summary["totals"]["estimated_cost_cny"], 8.7025)
            self.assertEqual(summary["totals"]["estimated_cost_usd"], 0.0)


class QualityDiagnosticsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for rel in ["01_大纲/章纲", "02_正文", "04_审核日志"]:
            (self.root / rel).mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_quality_diagnostics_writes_markdown_and_json(self) -> None:
        card = {
            "status": "confirmed",
            "core_event": "郁时谌收到未来礼物",
            "emotional_curve": "怀疑到警觉",
            "ending_hook": "门外出现未知信封",
            "forbidden": ["不要暴露寄件人"],
            "foreshadowing_planted": ["未来礼物的寄件人身份"],
        }
        (self.root / "01_大纲" / "章纲" / "第001章_task_card.json").write_text(
            json.dumps(card, ensure_ascii=False),
            encoding="utf-8",
        )
        text = (
            "# 第001章：礼物\n\n"
            "郁时谌收到未来礼物时，不禁看向窗外。他说：“数据呢？”\n\n"
            "沈逐光没有回答，只把信封推到桌边。门外忽然响起电话声，屏幕上只有一个问题：谁寄来的？"
        )

        md_path, json_path, report = write_quality_diagnostics(self.root, 1, text, "02_正文/第001章_草稿.md")

        self.assertTrue(md_path.exists())
        self.assertTrue(json_path.exists())
        self.assertIn("章节质量诊断", md_path.read_text(encoding="utf-8"))
        self.assertGreater(report["metrics"]["dialogue_turns"], 0)
        self.assertEqual(report["cliches"]["不禁"], 1)
        self.assertTrue(report["task_card_alignment"]["available"])
        self.assertIn("polish_targets", report)
        self.assertIn("重点精修片段", md_path.read_text(encoding="utf-8"))
        self.assertTrue((self.root / "04_审核日志" / "第001章_改稿清单.md").exists())

    def test_quality_diagnostics_flags_forbidden_terms(self) -> None:
        (self.root / "01_大纲" / "章纲" / "第001章_task_card.json").write_text(
            json.dumps({"status": "confirmed", "forbidden": ["提前揭露真相"]}, ensure_ascii=False),
            encoding="utf-8",
        )

        report = analyze_chapter_quality(self.root, 1, "他提前揭露真相。门外没人。", "02_正文/第001章_草稿.md")

        self.assertIn("提前揭露真相", report["task_card_alignment"]["forbidden_hits"])
        self.assertTrue(any(item["item"] == "触碰任务卡禁止事项" for item in report["findings"]))

    def test_quality_diagnostics_flags_flat_exposition(self) -> None:
        sentence = "他知道这件事很重要，因为规则是这样，事实上这意味着所有人都需要等待解释。"
        text = "。".join([sentence] * 16) + "。"

        report = analyze_chapter_quality(self.root, 1, text, "02_正文/第001章_草稿.md")
        finding_names = {item["item"] for item in report["findings"]}

        self.assertIn("冲突信号偏弱", finding_names)
        self.assertIn("角色主动性偏弱", finding_names)
        self.assertIn("说明性句子偏多", finding_names)
        self.assertIn("章首抓力偏弱", finding_names)
        self.assertIn("章末余味偏弱", finding_names)
        self.assertGreater(report["metrics"]["exposition_sentence_ratio"], 0.35)
        # 新语义：单纯文气/钩子偏弱不再触发自动改稿，避免模型为了过指标妥协质感。
        # 这里没有 forbidden 命中也没有任务卡核心事件未覆盖，所以不该触发。
        self.assertFalse(quality_needs_revision(report))

    def test_quality_caveat_downgrades_conflict_findings_for_interior_mode(self) -> None:
        (self.root / "01_大纲" / "章纲" / "第001章_task_card.json").write_text(
            json.dumps({"chapter_mode": "interior", "pacing": "slow_burn"}, ensure_ascii=False),
            encoding="utf-8",
        )
        text = "他坐在窗边，想起那些没有说出口的话。雨声一层一层落下来。" * 20

        report = analyze_chapter_quality(self.root, 1, text, "02_正文/第001章_草稿.md")
        conflict = [item for item in report["findings"] if item["item"] == "冲突信号偏弱"]

        self.assertIsNotNone(report["score_caveat"])
        self.assertEqual(conflict, [])
        self.assertEqual(report["metrics"]["chapter_mode_thresholds"]["conflict_min"], 0.0)

    def test_cliche_terms_are_context_sensitive(self) -> None:
        tense = "血从门缝里渗出来，脚步声逼近。他深吸一口气，抓起钥匙往后退。"
        quiet = "窗外的雨很慢，他深吸一口气，继续看那封没有署名的信。"

        tense_report = analyze_chapter_quality(self.root, 1, tense, "02_正文/第001章_草稿.md")
        quiet_report = analyze_chapter_quality(self.root, 1, quiet, "02_正文/第001章_草稿.md")

        self.assertNotIn("深吸一口气", tense_report["cliches"])
        self.assertIn("深吸一口气", quiet_report["cliches"])

    def test_chapter_mode_thresholds_allow_atmosphere_without_conflict_warning(self) -> None:
        (self.root / "01_大纲" / "章纲" / "第001章_task_card.json").write_text(
            json.dumps({"chapter_mode": "atmosphere", "ending_style": "open"}, ensure_ascii=False),
            encoding="utf-8",
        )
        text = (
            "雨停在凌晨两点。窗缝里还挂着水声，像有人把一串旧钥匙慢慢拖过墙面。"
            "他站在桌前，没有立刻碰那只信封。纸面被水汽泡皱，边角却干净得过分。"
            "灯影落在杯底，像一枚被压扁的眼睛。"
        ) * 8

        report = analyze_chapter_quality(self.root, 1, text, "02_正文/第001章_草稿.md")
        active_items = {item["item"] for item in report["findings"] if item["level"] != "accepted_by_writer"}

        self.assertEqual(report["metrics"]["chapter_mode"], "atmosphere")
        self.assertNotIn("冲突信号偏弱", active_items)

    def test_style_profile_override_allows_wang_xiaobo_silence_but_not_other_cliche(self) -> None:
        (self.root / "01_大纲" / "章纲" / "第001章_task_card.json").write_text(
            json.dumps({"style_profile": "wang_xiaobo"}, ensure_ascii=False),
            encoding="utf-8",
        )
        text = "大家陷入沉默。这个沉默很有组织性，只是后来一股情绪涌上心头。" * 6

        report = analyze_chapter_quality(self.root, 1, text, "02_正文/第001章_草稿.md")

        self.assertNotIn("陷入沉默", report["cliches"])
        self.assertIn("涌上心头", report["cliches"])

    def test_writer_overrides_mark_finding_and_remove_revision_brief(self) -> None:
        report = {
            "score": 60,
            "grade": "需打磨",
            "findings": [
                {"level": "warning", "item": "冲突信号偏弱", "detail": "请补冲突。"},
                {"level": "warning", "item": "任务卡对齐不足", "detail": "核心事件缺失。"},
            ],
            "metrics": {},
            "task_card_alignment": {"available": False},
        }

        updated = apply_writer_overrides(
            report,
            [{"rejected_advice": "冲突信号偏弱", "writer_reason": "本章刻意保留氛围。"}],
        )
        brief = render_revision_brief(updated)
        checklist = build_revision_checklist(updated)

        self.assertEqual(updated["findings"][0]["level"], "accepted_by_writer")
        self.assertGreater(updated["score"], 60)
        self.assertIn("禁止执行", brief)
        self.assertNotIn("请补冲突。", brief)
        self.assertFalse(any(row["问题"] == "冲突信号偏弱" for row in checklist))

    def test_writer_override_roundtrip_file(self) -> None:
        path = write_writer_override(
            self.root,
            1,
            rejected_advice="角色主动性偏弱",
            writer_reason="前期银行壳必须温吞。",
        )

        rows = read_writer_overrides(self.root, 1)

        self.assertTrue(path.exists())
        self.assertEqual(rows[0]["rejected_advice"], "角色主动性偏弱")
        self.assertIn("银行壳", rows[0]["writer_reason"])

    def test_open_ending_satisfies_ending_check(self) -> None:
        (self.root / "01_大纲" / "章纲" / "第001章_task_card.json").write_text(
            json.dumps({"ending_style": "open"}, ensure_ascii=False),
            encoding="utf-8",
        )
        text = "他没有再解释。窗外的灯熄了，远处的水声一直没有停。" * 12

        report = analyze_chapter_quality(self.root, 1, text, "02_正文/第001章_草稿.md")
        finding_names = {item["item"] for item in report["findings"]}

        self.assertIn("灯熄了", report["metrics"]["ending_open_hits"])
        self.assertNotIn("章末钩子偏弱", finding_names)

    def test_opening_and_ending_hook_scores_track_reader_pull(self) -> None:
        weak_text = (
            "他知道这件事很重要，因为规则是这样，事实上这意味着所有人都需要等待解释。"
            "他知道过去很复杂，因为每个人都知道这些规则原本如此。"
        ) * 8
        strong_text = (
            "雨水敲在窗上，郁时谌的指尖停在旧信边缘。信封背面的编号来自明天：谁把他的名字写进失踪档案？"
            "他决定把照片藏进袖口，转身逼问沈逐光。"
            "沈逐光没有回答，只把钥匙推到灯下。钥匙齿痕里有一线干涸的血，日期却来自未来。"
        ) * 5

        weak = analyze_chapter_quality(self.root, 1, weak_text, "02_正文/第001章_草稿.md")
        strong = analyze_chapter_quality(self.root, 1, strong_text, "02_正文/第001章_草稿.md")

        self.assertIn("opening_hook_score", weak["metrics"])
        self.assertIn("ending_hook_score", weak["metrics"])
        self.assertGreater(strong["metrics"]["opening_hook_score"], weak["metrics"]["opening_hook_score"])
        self.assertGreater(strong["metrics"]["ending_hook_score"], weak["metrics"]["ending_hook_score"])
        self.assertIn("章首抓力", render_quality_markdown(strong))

    def test_polish_targets_pinpoint_weak_passages(self) -> None:
        text = (
            "他知道这件事很重要，因为规则是这样，事实上这意味着所有人都需要等待解释。"
            "他知道所有答案都很复杂，因为过去一直如此，原来他们只能继续等待。"
            "空气仿佛凝固，他不禁陷入沉默。\n\n"
            "门外响起电话，他决定追问。"
        )

        targets = build_polish_targets(text)
        request = polish_targets_to_assist_request(targets)

        self.assertTrue(targets)
        self.assertEqual(targets[0]["位置"], "段落 1")
        self.assertIn("章首抓力弱", targets[0]["问题"])
        self.assertIn("解释密集", targets[0]["问题"])
        self.assertIn("套话", targets[0]["问题"])
        self.assertIn("## 重点精修片段", request)
        self.assertIn("原文片段", request)

    def test_quality_diagnostics_reports_reader_grip_radar(self) -> None:
        strong_text = (
            "雨水敲在窗上，郁时谌的指尖停在旧信边缘。"
            "他决定把照片藏进袖口，转身逼问沈逐光：这串编号为什么出现在失踪档案里？"
            "沈逐光没有回答，只把钥匙推到灯下。钥匙齿痕里有一线干涸的血，日期却来自未来。"
        ) * 8
        flat_text = "他知道事情很重要，因为规则是这样，事实上这意味着所有人都需要等待解释。" * 12

        strong = analyze_chapter_quality(self.root, 1, strong_text, "02_正文/第001章_草稿.md")
        flat = analyze_chapter_quality(self.root, 1, flat_text, "02_正文/第001章_草稿.md")

        self.assertIn("reader_grip_score", strong["metrics"])
        self.assertGreater(strong["metrics"]["reader_grip_score"], flat["metrics"]["reader_grip_score"])
        self.assertIn("好看度雷达", render_quality_markdown(strong))

    def test_revision_checklist_prioritizes_actionable_fixes(self) -> None:
        report = {
            "chapter_number": 1,
            "score": 55,
            "grade": "需打磨",
            "source_markdown_path": "02_正文/第001章_草稿.md",
            "metrics": {
                "page_turner_score": 28,
                "prose_texture_score": 40,
                "exposition_sentence_ratio": 0.5,
                "cliche_total": 2,
                "repeated_terms": [],
            },
            "findings": [{"level": "warning", "item": "章末钩子偏弱", "detail": "末尾没有下一章驱动力。"}],
            "task_card_alignment": {
                "available": True,
                "checks": [{"label": "核心事件", "covered": False, "value": "收到未来礼物"}],
                "forbidden_hits": ["提前揭露真相"],
                "foreshadowing_planted": 2,
                "foreshadowing_visible": 0,
            },
            "cliches": {"不禁": 2},
        }

        checklist = build_revision_checklist(report)
        request = checklist_to_assist_request(checklist)

        self.assertEqual(checklist[0]["优先级"], "P0")
        self.assertEqual(checklist[0]["问题"], "触碰任务卡禁止事项")
        self.assertTrue(any(row["问题"] == "补齐核心事件" for row in checklist))
        self.assertTrue(any(row["问题"] == "追读张力偏弱" for row in checklist))
        self.assertIn("## 改稿清单", request)
        self.assertIn("## 可直接采用文本", request)

    def test_quality_revision_brief_summarizes_actionable_items(self) -> None:
        report = {
            "score": 62,
            "grade": "需打磨",
            "metrics": {
                "dialogue_ratio": 0.02,
                "avg_sentence_zh_chars": 64,
                "sentence_length_stdev": 3,
                "long_sentences_over_80": 2,
                "long_paragraphs_over_260": 1,
                "cliche_total": 3,
                "repeated_terms": [{"term": "未来", "count": 8}],
                "page_turner_score": 30,
                "prose_texture_score": 42,
                "reader_grip_score": 35,
            },
            "findings": [{"level": "warning", "item": "章末钩子偏弱", "detail": "末尾缺少追读驱动力。"}],
            "task_card_alignment": {
                "available": True,
                "checks": [{"label": "章末钩子", "covered": False, "value": "门外出现未知信封"}],
                "forbidden_hits": ["提前揭露真相"],
                "foreshadowing_planted": 2,
                "foreshadowing_visible": 0,
            },
            "cliches": {"不禁": 2},
        }

        brief = render_revision_brief(report)

        self.assertTrue(quality_needs_revision(report))
        self.assertIn("章末钩子偏弱", brief)
        self.assertIn("提前揭露真相", brief)
        self.assertIn("任务卡对齐", brief)


class RAGTests(unittest.TestCase):
    def test_rag_mock_context_handles_empty_collections(self) -> None:
        old_mode = os.environ.get("NOVEL_RAG_MODE")
        os.environ["NOVEL_RAG_MODE"] = "mock"
        try:
            from rag_engine import NovelRAG

            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
                rag = NovelRAG(tmp)
                context = rag.build_context("测试章纲")
                self.assertIn("相关世界设定", context)
                self.assertIn("暂无可检索内容", context)
                del rag
                gc.collect()
        finally:
            if old_mode is None:
                os.environ.pop("NOVEL_RAG_MODE", None)
            else:
                os.environ["NOVEL_RAG_MODE"] = old_mode

    def test_reindex_all_indexes_global_outline(self) -> None:
        old_mode = os.environ.get("NOVEL_RAG_MODE")
        os.environ["NOVEL_RAG_MODE"] = "mock"
        try:
            from rag_engine import NovelRAG

            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
                root = Path(tmp)
                (root / "01_大纲").mkdir(parents=True)
                (root / "01_大纲" / "总纲.md").write_text("# 总纲\n主线必须围绕旧案推进。", encoding="utf-8")
                rag = NovelRAG(root)
                rag.reindex_all()
                data = rag.settings.get(ids=["global_outline"], include=["documents"])
                self.assertIn("主线必须围绕旧案推进", data["documents"][0])
                del rag
                gc.collect()
        finally:
            if old_mode is None:
                os.environ.pop("NOVEL_RAG_MODE", None)
            else:
                os.environ["NOVEL_RAG_MODE"] = old_mode

    def test_reindex_all_indexes_volume_plans(self) -> None:
        old_mode = os.environ.get("NOVEL_RAG_MODE")
        os.environ["NOVEL_RAG_MODE"] = "mock"
        try:
            from rag_engine import NovelRAG

            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
                root = Path(tmp)
                (root / "01_大纲" / "卷纲").mkdir(parents=True)
                (root / "01_大纲" / "卷纲" / "第01卷.md").write_text(
                    "# 第01卷：未来礼物\n\n- 章节范围：001-050\n- 叙事功能：开局立局。",
                    encoding="utf-8",
                )
                rag = NovelRAG(root)
                rag.reindex_all()
                data = rag.settings.get(ids=["volume_01"], include=["documents"])
                self.assertIn("未来礼物", data["documents"][0])
                del rag
                gc.collect()
        finally:
            if old_mode is None:
                os.environ.pop("NOVEL_RAG_MODE", None)
            else:
                os.environ["NOVEL_RAG_MODE"] = old_mode

    def test_long_character_docs_are_chunked_with_metadata(self) -> None:
        old_mode = os.environ.get("NOVEL_RAG_MODE")
        os.environ["NOVEL_RAG_MODE"] = "mock"
        try:
            from rag_engine import CHUNK_CHAR_LIMIT, NovelRAG

            with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
                long_doc = "\n\n".join(
                    f"## 小节{i}\n" + ("关键设定A会影响郁时谌的选择。" * 90)
                    for i in range(1, 4)
                )
                rag = NovelRAG(tmp)
                rag.index_character("沈逐光", long_doc, "00_世界观/角色档案/沈逐光.md")

                data = rag.characters.get(include=["documents", "metadatas"])
                self.assertGreater(rag.characters.count(), 1)
                self.assertTrue(all(len(doc) <= CHUNK_CHAR_LIMIT for doc in data["documents"]))
                self.assertTrue(any(meta.get("source_path") == "00_世界观/角色档案/沈逐光.md" for meta in data["metadatas"]))
                del rag
                gc.collect()
        finally:
            if old_mode is None:
                os.environ.pop("NOVEL_RAG_MODE", None)
            else:
                os.environ["NOVEL_RAG_MODE"] = old_mode


class LongStructureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_default_volumes_create_range_templates(self) -> None:
        paths = ensure_default_volumes(self.root, count=2, chapters_per_volume=25)

        self.assertEqual(len(paths), 2)
        plans = list_volume_plans(self.root)
        self.assertEqual(plans[0].chapter_start, 1)
        self.assertEqual(plans[0].chapter_end, 25)
        self.assertEqual(plans[1].chapter_start, 26)
        self.assertEqual(active_volume_for_chapter(self.root, 30).volume_number, 2)

    def test_volume_axis_block_summarizes_volume_plans(self) -> None:
        ensure_default_volumes(self.root, count=1)

        block = volume_axis_block(self.root)

        self.assertIn("第01卷", block)
        self.assertIn("章节范围", block)


class BookManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.app = Path(self.tmp.name)
        (self.app / "05_项目管理").mkdir(parents=True)
        (self.app / "prompts").mkdir(parents=True)
        (self.app / "prompts" / "正文生成.md").write_text("# 正文 prompt", encoding="utf-8")
        (self.app / ".env.example").write_text("NOVEL_LLM_MODE=mock\n", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_create_book_initializes_project_and_sets_active(self) -> None:
        registry = ensure_book_registry(self.app)
        self.assertEqual(registry["active_id"], "root")

        book = create_book(self.app, "雨夜档案", brief="旧案与未来信件", activate=True)

        active = get_active_book(self.app)
        book_path = Path(book["resolved_path"])
        self.assertEqual(active["id"], book["id"])
        self.assertTrue((book_path / "00_世界观" / "世界观.md").exists())
        self.assertTrue((book_path / "01_大纲" / "章纲" / "第001章.md").exists())
        self.assertTrue((book_path / "prompts" / "正文生成.md").exists())
        self.assertGreaterEqual(len(list_books(self.app)), 2)

    def test_import_switch_and_remove_book_registry_entry(self) -> None:
        external = self.app / "external_project"
        (external / "01_大纲" / "章纲").mkdir(parents=True)
        (external / "01_大纲" / "章纲" / "第001章.md").write_text("# 第001章", encoding="utf-8")

        imported = import_book(self.app, external, title="外部书", activate=True)
        self.assertEqual(get_active_book(self.app)["id"], imported["id"])

        set_active_book(self.app, "root")
        removed = remove_book(self.app, imported["id"])

        self.assertEqual(removed["title"], "外部书")
        self.assertTrue(external.exists())
        self.assertNotIn(imported["id"], {item["id"] for item in list_books(self.app)})

    def test_rename_book_updates_registry_and_book_info(self) -> None:
        book = create_book(self.app, "旧书名", activate=True)

        renamed = rename_book(self.app, book["id"], "新书名")

        self.assertEqual(renamed["title"], "新书名")
        self.assertEqual(get_active_book(self.app)["title"], "新书名")
        info = Path(renamed["resolved_path"]) / "05_项目管理" / "书籍信息.md"
        self.assertTrue(info.read_text(encoding="utf-8").startswith("# 新书名"))


class WebUIHelperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.old_pipeline_project_dir = novel_pipeline.PROJECT_DIR
        self.old_webui_project_dir = webui.PROJECT_DIR
        novel_pipeline.PROJECT_DIR = self.root
        webui.PROJECT_DIR = self.root
        for rel in [
            "00_世界观/角色档案",
            "01_大纲/卷纲",
            "01_大纲/章纲",
            "02_正文",
            "03_滚动记忆",
            "04_审核日志",
            "prompts",
        ]:
            (self.root / rel).mkdir(parents=True, exist_ok=True)
        (self.root / "03_滚动记忆" / "最近摘要.md").write_text("", encoding="utf-8")
        (self.root / "03_滚动记忆" / "全局摘要.md").write_text("", encoding="utf-8")

    def tearDown(self) -> None:
        novel_pipeline.PROJECT_DIR = self.old_pipeline_project_dir
        webui.PROJECT_DIR = self.old_webui_project_dir
        self.tmp.cleanup()

    def test_scan_placeholders_flags_chapter_template(self) -> None:
        path = self.root / "01_大纲" / "章纲" / "第001章.md"
        path.write_text("# 第001章：【章节标题】\n- 视角人物：【主角名】\n", encoding="utf-8")

        findings = webui.scan_placeholders(["01_大纲/章纲/第001章.md"])

        self.assertEqual(len(findings), 2)
        self.assertEqual(findings[0]["file"], "01_大纲/章纲/第001章.md")

    def test_next_action_prioritizes_placeholders(self) -> None:
        state = {
            "outline": True,
            "task_card": False,
            "task_card_confirmed": False,
            "draft": False,
            "audit": False,
            "ai_check": False,
            "revised": False,
            "final": False,
            "memory_updated": False,
            "placeholders": [{"file": "x", "line": 1, "text": "【章节标题】"}],
        }

        self.assertIn("占位符", webui.next_action_for_state(state))

    def test_chapter_state_detects_memory_updated(self) -> None:
        (self.root / "01_大纲" / "章纲" / "第001章.md").write_text("真实章纲", encoding="utf-8")
        sync_task_card_from_outline(self.root, 1, "真实章纲")
        confirm_task_card(self.root, 1)
        (self.root / "02_正文" / "第001章_定稿.md").write_text("正文", encoding="utf-8")
        (self.root / "03_滚动记忆" / "最近摘要.md").write_text("## 第1章\n摘要", encoding="utf-8")
        (self.root / "03_滚动记忆" / "全局摘要.md").write_text("<!-- auto-chapter-001 -->", encoding="utf-8")

        state = webui.chapter_state(1)

        self.assertTrue(state["outline"])
        self.assertTrue(state["task_card_confirmed"])
        self.assertTrue(state["final"])
        self.assertTrue(state["memory_updated"])

    def test_openrouter_model_id_normalization_adds_anthropic_prefix(self) -> None:
        self.assertEqual(
            webui.normalize_openrouter_model_id("claude-4.6-opus"),
            "anthropic/claude-4.6-opus",
        )
        self.assertEqual(
            webui.normalize_openrouter_model_id("anthropic/claude-4.6-opus"),
            "anthropic/claude-4.6-opus",
        )
        self.assertEqual(
            webui.normalize_openrouter_model_id("openrouter/auto"),
            "openrouter/auto",
        )

    def test_custom_base_url_normalization_handles_letaicode(self) -> None:
        self.assertEqual(
            webui.normalize_custom_base_url("https://letaicode.cn/claude"),
            "https://letaicode.cn/claude/v1",
        )
        self.assertEqual(
            webui.normalize_custom_base_url("https://letaicode.cn/claude/v1/chat/completions"),
            "https://letaicode.cn/claude/v1",
        )
        self.assertIn("/claude/v1", webui.custom_base_url_warning("https://letaicode.cn/claude"))

    def test_webui_write_file_returns_path_and_archives_worldbuilding(self) -> None:
        path = webui.write_file("00_世界观/世界观.md", "第一版")
        self.assertTrue(path.exists())
        webui.write_file("00_世界观/世界观.md", "第二版")

        versions = list((self.root / "00_世界观" / "versions").glob("世界观_*.md"))
        self.assertEqual((self.root / "00_世界观" / "世界观.md").read_text(encoding="utf-8"), "第二版")
        self.assertEqual(len(versions), 1)

    def test_webui_write_env_returns_path(self) -> None:
        path = webui.write_env({"NOVEL_LLM_MODE": "mock"})

        self.assertTrue(path.exists())
        self.assertIn("NOVEL_LLM_MODE=mock", path.read_text(encoding="utf-8"))

    def test_set_active_project_syncs_pipeline_project_dir(self) -> None:
        other = self.root / "other_book"
        other.mkdir()

        webui.set_active_project(other)

        self.assertEqual(webui.PROJECT_DIR, other.resolve())
        self.assertEqual(novel_pipeline.PROJECT_DIR, other.resolve())

    def test_rename_character_profile_moves_file_updates_heading_and_archives(self) -> None:
        char_dir = self.root / "00_世界观" / "角色档案"
        (char_dir / "旧名.md").write_text("# 旧名\n\n## 基本信息\n- 定位：主角\n", encoding="utf-8")

        path = webui.rename_character_profile("旧名.md", "新名")

        self.assertEqual(path.name, "新名.md")
        self.assertFalse((char_dir / "旧名.md").exists())
        self.assertTrue((char_dir / "新名.md").exists())
        self.assertTrue((char_dir / "新名.md").read_text(encoding="utf-8").startswith("# 新名"))
        self.assertEqual(len(list((char_dir / "versions").glob("旧名_*.md"))), 1)

    def test_rename_character_profile_rejects_existing_target(self) -> None:
        char_dir = self.root / "00_世界观" / "角色档案"
        (char_dir / "旧名.md").write_text("# 旧名\n", encoding="utf-8")
        (char_dir / "新名.md").write_text("# 新名\n", encoding="utf-8")

        with self.assertRaises(FileExistsError):
            webui.rename_character_profile("旧名.md", "新名")

        self.assertTrue((char_dir / "旧名.md").exists())
        self.assertEqual((char_dir / "新名.md").read_text(encoding="utf-8"), "# 新名\n")

    def test_rename_character_profile_can_overwrite_existing_target_with_backups(self) -> None:
        char_dir = self.root / "00_世界观" / "角色档案"
        (char_dir / "旧名.md").write_text("# 旧名\n\n源档案", encoding="utf-8")
        (char_dir / "新名.md").write_text("# 新名\n\n将被覆盖", encoding="utf-8")

        path = webui.rename_character_profile("旧名.md", "新名", overwrite=True)

        self.assertEqual(path.name, "新名.md")
        self.assertFalse((char_dir / "旧名.md").exists())
        self.assertIn("源档案", (char_dir / "新名.md").read_text(encoding="utf-8"))
        self.assertNotIn("将被覆盖", (char_dir / "新名.md").read_text(encoding="utf-8"))
        self.assertEqual(len(list((char_dir / "versions").glob("旧名_*.md"))), 1)
        self.assertEqual(len(list((char_dir / "versions").glob("新名_*.md"))), 1)

    def test_delete_character_profile_moves_to_recycle_with_reason(self) -> None:
        char_dir = self.root / "00_世界观" / "角色档案"
        source = char_dir / "林渊.md"
        source.write_text("# 林渊\n\n调查者", encoding="utf-8")

        recycled = webui.delete_character_profile("林渊.md", reason="合并到主角档案")

        self.assertFalse(source.exists())
        self.assertTrue(recycled.exists())
        self.assertIn("99_回收站", str(recycled))
        self.assertEqual(recycled.read_text(encoding="utf-8"), "# 林渊\n\n调查者")
        self.assertEqual(
            recycled.with_suffix(recycled.suffix + ".reason.txt").read_text(encoding="utf-8"),
            "合并到主角档案\n",
        )

    def test_delete_character_profile_rejects_template(self) -> None:
        char_dir = self.root / "00_世界观" / "角色档案"
        template = char_dir / "角色模板.md"
        template.write_text("# 【角色名】\n", encoding="utf-8")

        with self.assertRaises(ValueError):
            webui.delete_character_profile("角色模板.md")

        self.assertTrue(template.exists())

    def test_writing_assist_saves_result_without_overwriting_chapter_text(self) -> None:
        class FakeLLM:
            def __init__(self):
                self.user_prompt = ""
                self.workflow = ""

            def assist_text(self, system_prompt: str, user_prompt: str, **kwargs):
                self.user_prompt = user_prompt
                self.workflow = kwargs.get("workflow", "")
                return "## 建议\n强化章末反问。\n\n## 可直接采用文本\n门外的影子没有回答。"

        (self.root / "05_项目管理").mkdir(exist_ok=True)
        (self.root / "05_项目管理" / "故事规格.md").write_text("# 故事规格\n旧案悬疑。", encoding="utf-8")
        (self.root / "01_大纲" / "章纲" / "第001章.md").write_text("# 第001章\n主角收到旧信。", encoding="utf-8")
        draft = self.root / "02_正文" / "第001章_草稿.md"
        draft.write_text("郁时谌看着旧信。", encoding="utf-8")
        fake = FakeLLM()

        path = webui.run_writing_assist(1, "卡点求助", "增强章末钩子", mock=True, llm=fake, use_rag=False)

        self.assertTrue(path.exists())
        self.assertIn("可直接采用文本", path.read_text(encoding="utf-8"))
        self.assertEqual(draft.read_text(encoding="utf-8"), "郁时谌看着旧信。")
        self.assertEqual(fake.workflow, "writing_assist_block")
        self.assertIn("增强章末钩子", fake.user_prompt)
        self.assertIn("郁时谌看着旧信", fake.user_prompt)

    def test_extract_adoptable_assist_text_prefers_direct_section(self) -> None:
        content = """## 建议
先压低对白。

## 可直接采用文本
门外的影子没有回答。

## 备注
不要提前解释影子身份。
"""

        self.assertEqual(webui.extract_adoptable_assist_text(content), "门外的影子没有回答。")

    def test_build_text_diff_marks_candidate_changes(self) -> None:
        diff = webui.build_text_diff("旧句。\n相同句。", "新句。\n相同句。", "当前稿", "辅助草案")

        self.assertIn("--- 当前稿", diff)
        self.assertIn("+++ 辅助草案", diff)
        self.assertIn("-旧句。", diff)
        self.assertIn("+新句。", diff)

    def test_chapter_outline_template_survives_removed_chapter_001(self) -> None:
        template = webui._chapter_outline_template(2)

        self.assertIn("# 第002章", template)
        self.assertIn("## 核心事件", template)
        self.assertNotEqual(template.strip(), "")

    def test_compare_assist_candidate_quality_reports_delta_and_warnings(self) -> None:
        (self.root / "01_大纲" / "章纲" / "第001章_task_card.json").write_text(
            json.dumps({"status": "confirmed", "forbidden": ["揭露父亲真相"]}, ensure_ascii=False),
            encoding="utf-8",
        )
        (self.root / "02_正文" / "第001章_草稿.md").write_text(
            "门外忽然传来电话声，他不能立刻回头，只能决定把旧信藏进袖口。"
            "雨水敲着窗，照片背面的血痕像秘密一样压住他的呼吸。" * 8,
            encoding="utf-8",
        )
        candidate = self.root / "02_正文" / "第001章_AI辅助草案_20260101_010101.md"
        candidate.write_text("他揭露父亲真相。", encoding="utf-8")

        comparison = webui.compare_assist_candidate_quality(1, candidate.relative_to(self.root))

        labels = [row["指标"] for row in comparison["rows"]]
        self.assertIn("总分", labels)
        self.assertIn("中文字数", labels)
        self.assertIn("章首抓力", labels)
        self.assertTrue(any("字数显著少于当前稿" in warning for warning in comparison["warnings"]))
        self.assertTrue(any("禁止事项" in warning for warning in comparison["warnings"]))
        char_row = next(row for row in comparison["rows"] if row["指标"] == "中文字数")
        self.assertTrue(char_row["变化"].startswith("-"))

    def test_assist_candidate_can_be_extracted_and_promoted_to_revision(self) -> None:
        assist = self.root / "04_审核日志" / "第001章_AI辅助_好看度精修_20260101_010101.md"
        assist.write_text(
            "## 建议\n强化追读。\n\n## 可直接采用文本\n门外的影子没有回答。\n",
            encoding="utf-8",
        )
        revised = self.root / "02_正文" / "第001章_修订稿.md"
        revised.write_text("旧修订稿", encoding="utf-8")

        candidate = webui.save_writing_assist_candidate(
            1,
            "04_审核日志/第001章_AI辅助_好看度精修_20260101_010101.md",
        )

        self.assertTrue(candidate.exists())
        self.assertEqual(candidate.parent, self.root / "02_正文")
        self.assertEqual(candidate.read_text(encoding="utf-8"), "门外的影子没有回答。")

        promoted = webui.promote_assist_candidate_to_revision(1, candidate.relative_to(self.root))

        self.assertEqual(promoted, revised)
        self.assertEqual(revised.read_text(encoding="utf-8"), "门外的影子没有回答。")
        backups = list((self.root / "02_正文" / "versions").glob("第001章_修订稿_*.md"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(encoding="utf-8"), "旧修订稿")

    def test_writing_assist_polish_uses_revise_route(self) -> None:
        class FakeLLM:
            def __init__(self):
                self.called = ""

            def revise_text(self, system_prompt: str, user_prompt: str, **kwargs):
                self.called = kwargs.get("workflow", "")
                return "润色结果"

        (self.root / "01_大纲" / "章纲" / "第001章.md").write_text("# 第001章\n", encoding="utf-8")
        fake = FakeLLM()

        path = webui.run_writing_assist(1, "润色改写", selected_text="原句", mock=True, llm=fake, use_rag=False)

        self.assertEqual(fake.called, "writing_assist_polish")
        self.assertEqual(path.read_text(encoding="utf-8"), "润色结果")

    def test_writing_assist_beautify_includes_quality_radar_context(self) -> None:
        class FakeLLM:
            def __init__(self):
                self.user_prompt = ""
                self.workflow = ""

            def revise_text(self, system_prompt: str, user_prompt: str, **kwargs):
                self.user_prompt = user_prompt
                self.workflow = kwargs.get("workflow", "")
                return "好看度精修结果"

        (self.root / "01_大纲" / "章纲" / "第001章.md").write_text("# 第001章\n", encoding="utf-8")
        (self.root / "04_审核日志" / "第001章_质量诊断.json").write_text(
            json.dumps({
                "score": 60,
                "grade": "需打磨",
                "metrics": {
                    "dialogue_ratio": 0.1,
                    "avg_sentence_zh_chars": 40,
                    "sentence_length_stdev": 5,
                    "long_sentences_over_80": 0,
                    "long_paragraphs_over_260": 0,
                    "cliche_total": 0,
                    "repeated_terms": [],
                    "conflict_signal_density_per_1k": 0.2,
                    "agency_signal_density_per_1k": 0.1,
                    "exposition_sentence_ratio": 0.4,
                    "page_turner_score": 28,
                    "prose_texture_score": 35,
                    "reader_grip_score": 31,
                },
                "findings": [{"level": "warning", "item": "追读张力偏弱", "detail": "缺少翻页理由。"}],
                "task_card_alignment": {"available": False},
                "cliches": {},
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        fake = FakeLLM()

        path = webui.run_writing_assist(1, "好看度精修", selected_text="原稿", mock=True, llm=fake, use_rag=False)

        self.assertEqual(fake.workflow, "writing_assist_beautify")
        self.assertIn("好看度雷达", fake.user_prompt)
        self.assertIn("追读张力偏弱", fake.user_prompt)
        self.assertEqual(path.read_text(encoding="utf-8"), "好看度精修结果")

    def test_hook_assist_package_creates_candidate_without_overwriting_revision(self) -> None:
        class FakeLLM:
            def __init__(self):
                self.user_prompt = ""
                self.workflow = ""

            def revise_text(self, system_prompt: str, user_prompt: str, **kwargs):
                self.user_prompt = user_prompt
                self.workflow = kwargs.get("workflow", "")
                return "## 建议\n增强第一处异常和最后一段余味。\n\n## 可直接采用文本\n门外忽然响起第二通电话，他把旧信压进袖口。"

        (self.root / "01_大纲" / "章纲" / "第001章.md").write_text("# 第001章\n收到旧信。", encoding="utf-8")
        revised = self.root / "02_正文" / "第001章_修订稿.md"
        revised.write_text("旧修订稿", encoding="utf-8")
        fake = FakeLLM()

        result = webui.run_hook_assist_package(1, mock=True, llm=fake, use_rag=False)

        self.assertEqual(fake.workflow, "writing_assist_hooks")
        self.assertIn("首尾钩子增强指令", fake.user_prompt)
        self.assertIn("完整章节修订稿", fake.user_prompt)
        self.assertTrue(result["quality_md"].exists())
        self.assertTrue(result["assist_path"].exists())
        self.assertTrue(result["candidate_path"].exists())
        self.assertEqual(
            result["candidate_path"].read_text(encoding="utf-8"),
            "门外忽然响起第二通电话，他把旧信压进袖口。",
        )
        self.assertEqual(revised.read_text(encoding="utf-8"), "旧修订稿")

    def test_beautify_assist_package_creates_candidate_without_overwriting_revision(self) -> None:
        class FakeLLM:
            def __init__(self):
                self.user_prompt = ""
                self.workflow = ""

            def revise_text(self, system_prompt: str, user_prompt: str, **kwargs):
                self.user_prompt = user_prompt
                self.workflow = kwargs.get("workflow", "")
                return "## 建议\n压缩解释，补出章末疑问。\n\n## 可直接采用文本\n门外第二次敲响时，他终于把那封旧信翻到背面。"

        (self.root / "01_大纲" / "章纲" / "第001章.md").write_text("# 第001章\n收到旧信。", encoding="utf-8")
        draft = self.root / "02_正文" / "第001章_草稿.md"
        draft.write_text("他知道这件事很重要，因为规则是这样，事实上这意味着所有人都需要等待解释。" * 12, encoding="utf-8")
        revised = self.root / "02_正文" / "第001章_修订稿.md"
        revised.write_text("旧修订稿", encoding="utf-8")
        fake = FakeLLM()

        result = webui.run_beautify_assist_package(1, mock=True, llm=fake, use_rag=False)

        self.assertEqual(fake.workflow, "writing_assist_beautify")
        self.assertIn("## 改稿清单", fake.user_prompt)
        self.assertIn("## 重点精修片段", fake.user_prompt)
        self.assertTrue(result["quality_md"].exists())
        self.assertTrue((self.root / "04_审核日志" / "第001章_改稿清单.md").exists())
        self.assertTrue(result["assist_path"].exists())
        self.assertTrue(result["candidate_path"].exists())
        self.assertEqual(
            result["candidate_path"].read_text(encoding="utf-8"),
            "门外第二次敲响时，他终于把那封旧信翻到背面。",
        )
        self.assertEqual(revised.read_text(encoding="utf-8"), "旧修订稿")


class FakeStructureLLM:
    def assist_text(self, system_prompt: str, user_prompt: str, **kwargs) -> str:
        workflow = kwargs.get("workflow", "")
        if workflow == "foreshadowing_extract":
            return '{"planted": ["主角没有注意到钥匙齿痕异常"], "resolved": ["解释旧照片日期异常"]}'
        if workflow == "scene_plan":
            return """
[
  {
    "chapter_number": 1,
    "scene_number": 1,
    "title": "钥匙出现",
    "pov_character": "林渊",
    "scene_goal": "让主角获得异常钥匙",
    "conflict": "他想忽视线索但被迫验证",
    "emotional_tone": "警觉",
    "required_information": ["钥匙齿痕异常"],
    "forbidden_information": ["不要揭露幕后真相"],
    "estimated_words": 800
  },
  {
    "chapter_number": 1,
    "scene_number": 2,
    "title": "档案缺页",
    "pov_character": "林渊",
    "scene_goal": "验证钥匙关联的旧档案",
    "conflict": "档案记录与记忆冲突",
    "emotional_tone": "怀疑",
    "required_information": ["档案缺页"],
    "forbidden_information": ["不要让主角凭空得知秘密"],
    "estimated_words": 1200
  }
]
"""
        if workflow == "character_state_update":
            return """
{
  "characters": [
    {
      "name": "林渊",
      "location": "旧城档案室",
      "physical_state": "淋雨后疲惫但可行动",
      "emotional_state": "警觉、怀疑",
      "known_information": ["钥匙齿痕异常"],
      "possessions": ["异常钥匙"],
      "goal": "验证旧档案缺页原因",
      "relationship_changes": ["开始怀疑档案管理员沈砚"]
    }
  ]
}
"""
        return "{}"


class StructuredStoreTests(unittest.TestCase):
    def test_parse_chapter_outline_to_task_card(self) -> None:
        outline = """# 第001章：雨夜

## 基本信息
- 视角人物：林渊
- 字数目标：3000-4000字
- 时间线：第一天夜里

## 核心事件
林渊收到一封不该存在的信。

## 情感弧线
警惕 -> 怀疑 -> 被迫行动

## 伏笔操作
- 埋下：【F001】照片日期异常
- 收回：无

## 章末悬念
门外有人敲门。

## 禁止事项
- 不要揭露父亲真相
"""
        card = parse_chapter_outline(1, outline, "outline.md")

        self.assertEqual(card.pov_character, "林渊")
        self.assertEqual(card.status, "draft")
        self.assertIn("F001", card.foreshadowing_planted[0])
        self.assertEqual(card.source_path, "outline.md")

    def test_parse_chapter_outline_to_v5_mode_fields(self) -> None:
        outline = """# 第002章：空房间

## 基本信息
- 章节模式：atmosphere
- 结尾方式：open
- 节奏：slow_burn
- 风格档案：wang_xiaobo
- 视角人物：郁时谌

## 核心事件
他看见空房间里多出一把椅子。
"""
        card = parse_chapter_outline(2, outline, "outline.md")

        self.assertEqual(card.chapter_mode, "atmosphere")
        self.assertEqual(card.ending_style, "open")
        self.assertEqual(card.pacing, "slow_burn")
        self.assertEqual(card.style_profile, "wang_xiaobo")

    def test_confirm_task_card_updates_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "01_大纲" / "章纲").mkdir(parents=True)
            outline = "# 第001章：雨夜\n\n## 核心事件\n收到信。"
            sync_task_card_from_outline(root, 1, outline)
            draft = read_task_card(root, 1)
            self.assertIsNotNone(draft)
            self.assertEqual(draft.status, "draft")

            confirmed = confirm_task_card(root, 1)

            self.assertEqual(confirmed.status, "confirmed")
            self.assertIsNotNone(confirmed.confirmed_at)

    def test_sync_task_card_preserves_confirmation_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "01_大纲" / "章纲").mkdir(parents=True)
            sync_task_card_from_outline(root, 1, "# 第001章：旧标题")
            confirm_task_card(root, 1)

            synced = sync_task_card_from_outline(root, 1, "# 第001章：新标题")

            self.assertEqual(synced.status, "confirmed")
            self.assertIsNotNone(synced.confirmed_at)
            self.assertIn("新标题", synced.title)

    def test_scene_plan_from_task_card_and_status_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "01_大纲" / "章纲").mkdir(parents=True)
            outline = "# 第001章：雨夜\n\n## 核心事件\n收到信。\n\n## 章末悬念\n门外敲门。"
            sync_task_card_from_outline(root, 1, outline)

            scenes = sync_scene_plan_from_task_card(root, 1)
            self.assertEqual(len(scenes), 3)
            self.assertTrue((root / "01_大纲" / "章纲" / "第001章_scenes" / "scene_plan.json").exists())

            update_scene_status(root, 1, 2, "drafted", "scene_002.md")
            updated = read_scene_plan(root, 1)
            self.assertEqual(updated[1].status, "drafted")
            self.assertEqual(updated[1].selected_draft_path, "scene_002.md")

    def test_llm_foreshadowing_hints_are_merged_into_task_card(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "01_大纲" / "章纲").mkdir(parents=True)
            outline = "# 第001章：雨夜\n\n## 核心事件\n主角收到钥匙但没有意识到齿痕异常。"

            card = sync_task_card_from_outline(root, 1, outline, llm=FakeStructureLLM())

            self.assertIn("主角没有注意到钥匙齿痕异常", card.foreshadowing_planted)
            self.assertIn("解释旧照片日期异常", card.foreshadowing_resolved)

    def test_llm_scene_plan_can_replace_fixed_three_scene_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "01_大纲" / "章纲").mkdir(parents=True)
            outline = "# 第001章：雨夜\n\n## 核心事件\n收到钥匙。"
            sync_task_card_from_outline(root, 1, outline)

            scenes = sync_scene_plan_from_task_card(root, 1, llm=FakeStructureLLM())

            self.assertEqual(len(scenes), 2)
            self.assertEqual(scenes[0].title, "钥匙出现")
            self.assertTrue((root / "01_大纲" / "章纲" / "第001章_scenes" / "scene_plan.json").exists())

    def test_character_state_update_writes_markdown_and_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "03_滚动记忆").mkdir(parents=True)

            result = update_character_states_with_llm(
                root,
                1,
                "林渊拿到异常钥匙，离开旧城档案室。",
                "- 核心事件：钥匙出现。",
                FakeStructureLLM(),
                "## 核心事件\n收到钥匙。",
            )

            states = read_character_states(root)
            self.assertTrue(result["markdown"].exists())
            self.assertTrue(result["json"].exists())
            self.assertIn("林渊", states)
            self.assertEqual(states["林渊"].location, "旧城档案室")
            self.assertIn("异常钥匙", states["林渊"].possessions)

    def test_character_state_prompt_includes_project_axis(self) -> None:
        class CaptureLLM:
            def __init__(self) -> None:
                self.user_prompt = ""

            def assist_text(self, system_prompt: str, user_prompt: str, **kwargs) -> str:
                self.user_prompt = user_prompt
                return '{"characters": []}'

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "03_滚动记忆").mkdir(parents=True)
            (root / "05_项目管理").mkdir(parents=True)
            (root / "05_项目管理" / "故事规格.md").write_text(
                "# 故事规格\n\n## 1. 一句话概括\n\n**回答**：郁时谌收到来自未来的礼物。\n",
                encoding="utf-8",
            )
            llm = CaptureLLM()

            update_character_states_with_llm(root, 1, "正文", "摘要", llm, "章纲")

            self.assertIn("项目轴", llm.user_prompt)
            self.assertIn("郁时谌", llm.user_prompt)
            self.assertIn("联动硬约束", llm.user_prompt)

    def test_reaudit_json_uses_custom_source_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = write_review_json_for_source(
                root,
                1,
                "本章未发现明显逻辑问题。",
                "critic",
                "04_审核日志/第001章_复审.md",
                target_id="ch001_reaudit",
            )

            self.assertTrue(path.name.endswith("复审.json"))
            self.assertIn("ch001_reaudit", path.read_text(encoding="utf-8"))

    def test_scene_draft_versions_and_selection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "01_大纲" / "章纲").mkdir(parents=True)
            (root / "02_正文" / "第001章_scenes").mkdir(parents=True)
            outline = "# 第001章：雨夜\n\n## 核心事件\n收到信。"
            sync_task_card_from_outline(root, 1, outline)
            sync_scene_plan_from_task_card(root, 1)

            self.assertEqual(next_scene_draft_version(root, 1, 1), 1)
            draft_v1 = root / "02_正文" / "第001章_scenes" / "scene_001_draft_v001.md"
            draft_v2 = root / "02_正文" / "第001章_scenes" / "scene_001_draft_v002.md"
            draft_v2.write_text("第二版", encoding="utf-8")
            draft_v1.write_text("第一版", encoding="utf-8")

            drafts = list_scene_drafts(root, 1, 1)
            self.assertEqual([path.name for path in drafts], ["scene_001_draft_v001.md", "scene_001_draft_v002.md"])
            self.assertEqual(next_scene_draft_version(root, 1, 1), 3)

            select_scene_draft(root, 1, 1, "02_正文/第001章_scenes/scene_001_draft_v002.md")
            updated = read_scene_plan(root, 1)
            self.assertEqual(updated[0].status, "selected")
            self.assertTrue(updated[0].selected_draft_path.endswith("scene_001_draft_v002.md"))


class ProjectCenterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for rel in [
            "00_世界观/角色档案",
            "01_大纲/章纲",
            "02_正文",
            "03_滚动记忆",
            "04_审核日志",
            "prompts",
        ]:
            (self.root / rel).mkdir(parents=True, exist_ok=True)
        (self.root / "00_世界观" / "世界观.md").write_text("# 世界观\n真实设定。", encoding="utf-8")
        (self.root / "00_世界观" / "文风档案.md").write_text("# 文风\n克制、清晰。", encoding="utf-8")
        (self.root / "01_大纲" / "总纲.md").write_text("# 总纲\n主线推进。", encoding="utf-8")
        (self.root / "01_大纲" / "章纲" / "第001章.md").write_text("# 第001章：雨夜\n\n## 核心事件\n收到信。", encoding="utf-8")
        (self.root / "03_滚动记忆" / "全局摘要.md").write_text("# 全局摘要", encoding="utf-8")
        (self.root / "03_滚动记忆" / "最近摘要.md").write_text("# 最近章节摘要", encoding="utf-8")
        (self.root / "03_滚动记忆" / "伏笔追踪.md").write_text("| 编号 | 埋入章节 | 伏笔内容 | 状态 | 计划回收章节 |\n|---|---|---|---|---|\n", encoding="utf-8")
        (self.root / "03_滚动记忆" / "人物状态表.md").write_text("# 人物状态表", encoding="utf-8")
        (self.root / "prompts" / "正文生成.md").write_text("正文 prompt", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_v1_project_center_creates_operational_docs(self) -> None:
        created = ensure_project_center(self.root)

        self.assertTrue(created)
        self.assertTrue((self.root / SPEC).exists())
        self.assertTrue((self.root / CLARIFY).exists())
        self.assertTrue((self.root / TASKS).exists())

    def test_v1_upgrade_generates_status_tasks_and_quality_report(self) -> None:
        report = run_v1_upgrade(self.root)

        self.assertEqual(report.version, "1.0")
        self.assertTrue((self.root / QUALITY).exists())
        self.assertTrue((self.root / "05_项目管理" / "project_status.json").exists())
        self.assertIn("第001章", (self.root / TASKS).read_text(encoding="utf-8"))

    def test_quality_report_flags_placeholders(self) -> None:
        ensure_project_center(self.root)
        (self.root / "01_大纲" / "章纲" / "第001章.md").write_text("# 第001章：【章节标题】\n", encoding="utf-8")

        path = generate_quality_report(self.root)
        report = build_project_status(self.root)

        self.assertIn("占位符", path.read_text(encoding="utf-8"))
        self.assertGreaterEqual(report.metrics["placeholders"], 1)

    def test_project_status_flags_missing_dramatic_diagnostics(self) -> None:
        ensure_project_center(self.root)
        (self.root / "02_正文" / "第001章_草稿.md").write_text("郁时谌必须选择。", encoding="utf-8")

        report = build_project_status(self.root)

        self.assertEqual(report.metrics["drama_diagnostics"], 0)
        self.assertTrue(any("缺少戏剧诊断" in item for item in report.warnings))

        (self.root / "04_审核日志" / "第001章_戏剧诊断.json").write_text(
            '{"chapter_number": 1, "pressure_curve_score": 50, "character_arc_score": 50, "cinematic_score": 50, "overall_drama_score": 50}',
            encoding="utf-8",
        )
        report = build_project_status(self.root)

        self.assertEqual(report.metrics["drama_diagnostics"], 1)
        self.assertFalse(any("缺少戏剧诊断" in item for item in report.warnings))

    def test_writing_tasks_cover_missing_task_card(self) -> None:
        ensure_project_center(self.root)
        path = generate_writing_tasks(self.root)

        self.assertIn("生成并确认第001章任务卡", path.read_text(encoding="utf-8"))

    def test_story_consistency_warns_when_axis_names_lack_character_files(self) -> None:
        ensure_project_center(self.root)
        (self.root / "00_世界观" / "角色档案" / "郁时谌.md").write_text("# 郁时谌", encoding="utf-8")
        (self.root / "01_大纲" / "总纲.md").write_text(
            "# 总纲\n\n| **女一·沈岁宜** | 资本方 |",
            encoding="utf-8",
        )

        warnings = collect_story_consistency_warnings(self.root)

        self.assertTrue(any("沈岁宜" in item for item in warnings))

    def test_character_roster_issues_catch_heroine_name_drift(self) -> None:
        ensure_project_center(self.root)
        char_dir = self.root / "00_世界观" / "角色档案"
        (self.root / "01_大纲" / "总纲.md").write_text(
            "\n".join([
                "# 总纲",
                "| 代号 | 年龄 | 功能 |",
                "|------|------|------|",
                "| **女一·沈岁宜** | 28 | 资本方 |",
                "| **女二·陆潮声** | 25 | 技术验证 |",
                "| **女三·姜漂** | 22 | 舆论 |",
                "| **女四·裴夜澜** | 30 | 合规 |",
                "| **女五·温故晚** | 18 | 私人生活 |",
                "| **中点** | 陆潮声质问技术来源 | 推进结构 |",
            ]),
            encoding="utf-8",
        )
        (char_dir / "沈逐光.md").write_text("# 沈逐光\n\n五女主中技术验证功能位。", encoding="utf-8")
        (char_dir / "温漪.md").write_text(
            "# 温漪\n\n本档案替代《总纲草案》中的“女三·姜漂”，温漪为五女主中媒体功能位。",
            encoding="utf-8",
        )
        (char_dir / "程栩白.md").write_text("# 程栩白\n\n五女主中产业化操盘手。", encoding="utf-8")
        (char_dir / "阮眠.md").write_text("# 阮眠\n\n五女主中情感牵引者。", encoding="utf-8")
        (char_dir / "纪若棠.md").write_text("# 纪若棠\n\n本档案坚守反派/对手功能位，不是五女主之一。", encoding="utf-8")

        issues = collect_character_roster_issues(self.root)
        messages = "\n".join(issue["message"] for issue in issues)
        warnings = "\n".join(collect_story_consistency_warnings(self.root))

        self.assertIn("沈岁宜", messages)
        self.assertIn("温故晚", messages)
        self.assertIn("沈逐光", messages)
        self.assertIn("温漪 替代 女三·姜漂", messages)
        self.assertNotIn("纪若棠", messages)
        self.assertNotIn("中点", warnings)

    def test_linkage_drift_flags_unsynced_story_spec_and_volume_ranges(self) -> None:
        ensure_project_center(self.root)
        (self.root / "05_项目管理" / "故事规格.md").write_text(
            "\n".join([
                "# 故事规格",
                "## 4. 主要角色",
                "- 主角：郁时谌",
                "- 反派/对手：待命名 · 掌握关键资源的人",
                "- 挚友/同伴：待命名 · 能指出主角盲点的人",
                "- 导师/障碍：待命名 · 知道旧事的人",
            ]),
            encoding="utf-8",
        )
        (self.root / "01_大纲" / "总纲.md").write_text(
            "\n".join([
                "# 总纲",
                "| 代号 | 功能 |",
                "|------|------|",
                "| 反派·韩既白 | 旧秩序维护者 |",
                "| 挚友·莫春山 | 指出主角盲点 |",
                "| 导师·贺长明 | 知道旧事 |",
                "### 第一幕：点火（第1章 - 第25章）",
                "### 第二幕：燃烧（第26章 - 第70章）",
                "### 第三幕：抉择（第71章 - 第95章）",
            ]),
            encoding="utf-8",
        )
        volume_dir = self.root / "01_大纲" / "卷纲"
        volume_dir.mkdir(parents=True, exist_ok=True)
        (volume_dir / "第01卷.md").write_text("# 第01卷：待命名\n\n- 章节范围：001-050\n- 本卷在全书中的结构任务：待补充", encoding="utf-8")
        (volume_dir / "第02卷.md").write_text("# 第02卷：待命名\n\n- 章节范围：051-100\n- 本卷在全书中的结构任务：待补充", encoding="utf-8")
        (volume_dir / "第03卷.md").write_text("# 第03卷：待命名\n\n- 章节范围：101-150\n- 本卷在全书中的结构任务：待补充", encoding="utf-8")

        messages = "\n".join(issue["message"] for issue in collect_linkage_drift_issues(self.root))

        self.assertIn("故事规格主要角色位", messages)
        self.assertIn("韩既白", messages)
        self.assertIn("莫春山", messages)
        self.assertIn("贺长明", messages)
        self.assertIn("卷纲仍是模板", messages)
        self.assertIn("卷纲章节范围未承接总纲幕结构", messages)
        self.assertIn("第1-25章", messages)
        self.assertIn("第03卷.md=第101-150章", messages)

    def test_linkage_drift_flags_character_sync_declarations_not_landed(self) -> None:
        ensure_project_center(self.root)
        char_dir = self.root / "00_世界观" / "角色档案"
        (self.root / "05_项目管理" / "故事规格.md").write_text("# 故事规格\n\n主角：郁时谌", encoding="utf-8")
        (self.root / "01_大纲" / "总纲.md").write_text("# 总纲\n\n| 女三·姜漂 | 舆论功能 |", encoding="utf-8")
        (char_dir / "温漪.md").write_text(
            "# 温漪\n\n## 功能替换声明\n\n本档案替代《总纲草案》中的“女三·姜漂”。请同步更新总纲和故事规格。",
            encoding="utf-8",
        )

        messages = "\n".join(issue["message"] for issue in collect_linkage_drift_issues(self.root))

        self.assertIn("角色档案含同步声明", messages)
        self.assertIn("温漪", messages)
        self.assertIn("总纲/故事规格", messages)

    def test_outline_review_prepends_local_consistency_warnings(self) -> None:
        ensure_project_center(self.root)
        (self.root / "00_世界观" / "角色档案" / "沈逐光.md").write_text(
            "# 沈逐光\n\n五女主中技术验证功能位。",
            encoding="utf-8",
        )
        (self.root / "01_大纲" / "总纲.md").write_text(
            "# 总纲\n\n| **女一·沈岁宜** | 资本方 |",
            encoding="utf-8",
        )

        class CaptureRouter:
            def __init__(self, project_dir: Path):
                self.project_dir = project_dir
                self.user_prompt = ""

            def critic_text(self, system_prompt: str, user_prompt: str, **kwargs) -> str:
                self.user_prompt = user_prompt
                return "LLM 审查意见"

        captured = CaptureRouter(self.root)
        old_router = planning_assist.LLMRouter
        planning_assist.LLMRouter = lambda project_dir: captured
        try:
            result = planning_assist.review_global_outline(self.root, mock=True)
        finally:
            planning_assist.LLMRouter = old_router

        self.assertIn("本地一致性预警", result)
        self.assertIn("沈岁宜", result)
        self.assertIn("正式角色档案", captured.user_prompt)
        self.assertIn("LLM 审查意见", result)


class WorkflowAdvisorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for rel in [
            "00_世界观/角色档案",
            "01_大纲/章纲",
            "02_正文",
            "03_滚动记忆",
            "04_审核日志",
        ]:
            (self.root / rel).mkdir(parents=True, exist_ok=True)
        (self.root / "03_滚动记忆" / "全局摘要.md").write_text("# 全局摘要", encoding="utf-8")
        (self.root / "03_滚动记忆" / "最近摘要.md").write_text("# 最近摘要", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_recommendation_blocks_placeholder_outline(self) -> None:
        (self.root / "01_大纲" / "章纲" / "第001章.md").write_text("# 第001章：【章节标题】", encoding="utf-8")

        flow = chapter_flow(self.root, 1)

        self.assertEqual(flow["recommendation"]["action"], "edit_outline")
        self.assertEqual(flow["recommendation"]["severity"], "blocked")

    def test_recommendation_moves_from_task_card_to_scene_pipeline(self) -> None:
        outline = "# 第001章：雨夜\n\n## 核心事件\n收到信。\n\n## 章末悬念\n门外敲门。"
        (self.root / "01_大纲" / "章纲" / "第001章.md").write_text(outline, encoding="utf-8")

        self.assertEqual(chapter_flow(self.root, 1)["recommendation"]["action"], "generate_volume_outline")
        volume_dir = self.root / "01_大纲" / "卷纲"
        volume_dir.mkdir(parents=True, exist_ok=True)
        volume = (
            "# 第01卷：雨夜开局\n\n"
            "## 卷定位\n- 章节范围：001-050\n- 叙事功能：立局。\n\n"
            "## 核心冲突\n- 外部压力：旧案重启。\n\n"
            "## 角色弧线\n- 主角：从逃避到追查。\n\n"
            "## 伏笔预算\n- 本卷必须埋下：雨夜来信。\n\n"
            "## 节奏目标\n- 开端：收到信。\n\n"
            "## 卷末状态\n- 未解决问题：寄信人身份。\n"
        )
        (volume_dir / "第01卷.md").write_text(volume, encoding="utf-8")
        self.assertEqual(chapter_flow(self.root, 1)["recommendation"]["action"], "review_volume_outline")
        volume_hash = hashlib.sha256(volume.encode("utf-8")).hexdigest()
        review_dir = self.root / "AI审查缓存"
        review_dir.mkdir(parents=True, exist_ok=True)
        (review_dir / "outline_outline_卷纲_第01卷.md.md").write_text("卷纲审查意见", encoding="utf-8")
        self.assertEqual(chapter_flow(self.root, 1)["recommendation"]["action"], "improve_volume_outline")
        (review_dir / "outline_outline_卷纲_第01卷.md_improved.json").write_text(
            json.dumps({"volume_hash": volume_hash}, ensure_ascii=False),
            encoding="utf-8",
        )
        self.assertEqual(chapter_flow(self.root, 1)["recommendation"]["action"], "review_outline")
        review_dir = self.root / "AI审查缓存"
        review_dir.mkdir(parents=True, exist_ok=True)
        (review_dir / "outline_outline_章纲_1.md").write_text("章纲审查意见", encoding="utf-8")
        self.assertEqual(chapter_flow(self.root, 1)["recommendation"]["action"], "improve_outline")
        (review_dir / "outline_outline_章纲_1_improved.json").write_text(
            json.dumps({"outline_hash": hashlib.sha256(outline.encode("utf-8")).hexdigest()}),
            encoding="utf-8",
        )
        self.assertEqual(chapter_flow(self.root, 1)["recommendation"]["action"], "generate_task_card")
        sync_task_card_from_outline(self.root, 1, outline)
        self.assertEqual(chapter_flow(self.root, 1)["recommendation"]["action"], "confirm_task_card")
        confirm_task_card(self.root, 1)
        self.assertEqual(chapter_flow(self.root, 1)["recommendation"]["action"], "plan_scenes")
        sync_scene_plan_from_task_card(self.root, 1)
        self.assertEqual(chapter_flow(self.root, 1)["recommendation"]["action"], "draft_scene")

    def test_volume_outline_only_blocks_first_chapter_of_volume(self) -> None:
        outline = "# 第002章：雨声\n\n## 核心事件\n继续追查。\n\n## 章末悬念\n旧信复现。"
        (self.root / "01_大纲" / "章纲" / "第002章.md").write_text(outline, encoding="utf-8")

        flow = chapter_flow(self.root, 2)

        self.assertFalse(flow["volume"]["required"])
        self.assertEqual(flow["recommendation"]["action"], "review_outline")

    def test_missing_next_volume_blocks_on_first_chapter_of_new_volume(self) -> None:
        outline = "# 第051章：新卷\n\n## 核心事件\n进入新的城市。\n\n## 章末悬念\n陌生人认出主角。"
        (self.root / "01_大纲" / "章纲" / "第051章.md").write_text(outline, encoding="utf-8")
        volume_dir = self.root / "01_大纲" / "卷纲"
        volume_dir.mkdir(parents=True, exist_ok=True)
        (volume_dir / "第01卷.md").write_text(
            "# 第01卷：开局\n\n## 卷定位\n- 章节范围：001-050\n\n## 核心冲突\n旧案。\n\n## 角色弧线\n追查。\n\n## 伏笔预算\n旧信。\n\n## 卷末状态\n离开。",
            encoding="utf-8",
        )

        flow = chapter_flow(self.root, 51)

        self.assertTrue(flow["volume"]["required"])
        self.assertEqual(flow["volume"]["volume_name"], "第02卷.md")
        self.assertEqual(flow["recommendation"]["action"], "generate_volume_outline")

    def test_recommendation_assembles_when_all_scenes_have_drafts(self) -> None:
        outline = "# 第001章：雨夜\n\n## 核心事件\n收到信。"
        (self.root / "01_大纲" / "章纲" / "第001章.md").write_text(outline, encoding="utf-8")
        sync_task_card_from_outline(self.root, 1, outline)
        confirm_task_card(self.root, 1)
        scenes = sync_scene_plan_from_task_card(self.root, 1)
        scene_dir = self.root / "02_正文" / "第001章_scenes"
        scene_dir.mkdir(parents=True)
        for scene in scenes:
            (scene_dir / f"scene_{scene.scene_number:03d}_draft_v001.md").write_text("正文", encoding="utf-8")

        flow = chapter_flow(self.root, 1)

        self.assertEqual(flow["recommendation"]["action"], "assemble_scenes")

    def test_recommendation_runs_reader_mirror_before_quality(self) -> None:
        """精简后：审计 → 读者镜像 → 质量诊断。ai_check / deep_check 已被砍。"""
        outline = "# 第001章：雨夜\n\n## 核心事件\n收到信。"
        (self.root / "01_大纲" / "章纲" / "第001章.md").write_text(outline, encoding="utf-8")
        sync_task_card_from_outline(self.root, 1, outline)
        confirm_task_card(self.root, 1)
        scenes = sync_scene_plan_from_task_card(self.root, 1)
        scene_dir = self.root / "02_正文" / "第001章_scenes"
        scene_dir.mkdir(parents=True)
        for scene in scenes:
            (scene_dir / f"scene_{scene.scene_number:03d}_draft_v001.md").write_text("场景正文", encoding="utf-8")
        (self.root / "02_正文" / "第001章_草稿.md").write_text("他收到信。", encoding="utf-8")
        (self.root / "04_审核日志" / "第001章_审计.md").write_text("本章未发现明显逻辑问题。", encoding="utf-8")

        flow = chapter_flow(self.root, 1)

        self.assertEqual(flow["recommendation"]["action"], "reader_mirror")
        (self.root / "04_审核日志" / "第001章_读者镜像.md").write_text("追看欲尚可。", encoding="utf-8")

        flow = chapter_flow(self.root, 1)

        self.assertEqual(flow["recommendation"]["action"], "quality_diag")
        step_names = [step["name"] for step in flow["steps"]]
        self.assertIn("读者镜像", step_names)
        self.assertIn("诊断", step_names)
        self.assertNotIn("AI味", step_names)
        self.assertNotIn("深审", step_names)

    def test_recommendation_walks_through_v5_diagnostic_stages(self) -> None:
        """plot 模式（默认）：质量诊断 → 戏剧诊断 → 文学批评 → 风格法庭 → 声音诊断 → 编辑备忘录。"""
        outline = "# 第001章：雨夜\n\n## 核心事件\n收到信。"
        (self.root / "01_大纲" / "章纲" / "第001章.md").write_text(outline, encoding="utf-8")
        sync_task_card_from_outline(self.root, 1, outline)
        confirm_task_card(self.root, 1)
        scenes = sync_scene_plan_from_task_card(self.root, 1)
        scene_dir = self.root / "02_正文" / "第001章_scenes"
        scene_dir.mkdir(parents=True)
        for scene in scenes:
            (scene_dir / f"scene_{scene.scene_number:03d}_draft_v001.md").write_text("场景正文", encoding="utf-8")
        (self.root / "02_正文" / "第001章_草稿.md").write_text("他收到信。", encoding="utf-8")
        for rel in ["审计", "读者镜像", "质量诊断"]:
            (self.root / "04_审核日志" / f"第001章_{rel}.md").write_text(f"# {rel}", encoding="utf-8")
        (self.root / "04_审核日志" / "第001章_质量诊断.json").write_text(
            json.dumps({"score": 92, "findings": []}, ensure_ascii=False), encoding="utf-8",
        )

        # 1. 质量诊断完成、plot 模式 → 推戏剧诊断
        self.assertEqual(chapter_flow(self.root, 1)["recommendation"]["action"], "drama_diag")
        (self.root / "04_审核日志" / "第001章_戏剧诊断.md").write_text("# 戏剧诊断", encoding="utf-8")
        # 2. 戏剧诊断完成 → 推文学批评
        self.assertEqual(chapter_flow(self.root, 1)["recommendation"]["action"], "literary_critic")
        (self.root / "04_审核日志" / "第001章_文学批评.md").write_text("# 文学批评", encoding="utf-8")
        # 3. 文学批评完成 → 推风格法庭
        self.assertEqual(chapter_flow(self.root, 1)["recommendation"]["action"], "style_court")
        (self.root / "04_审核日志" / "第001章_风格法庭.md").write_text("# 风格法庭", encoding="utf-8")
        # 4. 风格法庭完成 → 推声音诊断
        self.assertEqual(chapter_flow(self.root, 1)["recommendation"]["action"], "voice_diag")
        (self.root / "04_审核日志" / "第001章_声音诊断.md").write_text("# 声音诊断", encoding="utf-8")
        # 5. 声音诊断完成 → 推编辑备忘录
        self.assertEqual(chapter_flow(self.root, 1)["recommendation"]["action"], "editor_memo")
        (self.root / "04_审核日志" / "第001章_编辑备忘录.md").write_text("# 编辑备忘录", encoding="utf-8")
        # 6. 编辑备忘录完成、无硬伤 → 进入 save_final
        self.assertEqual(chapter_flow(self.root, 1)["recommendation"]["action"], "save_final")

    def test_recommendation_skips_drama_diag_for_interior_chapter(self) -> None:
        """interior / atmosphere / bridge 模式跳过戏剧诊断，避免量化指标抹平克制氛围。"""
        outline = "# 第001章：雨夜\n\n## 核心事件\n他坐着没动。"
        (self.root / "01_大纲" / "章纲" / "第001章.md").write_text(outline, encoding="utf-8")
        sync_task_card_from_outline(self.root, 1, outline)
        confirm_task_card(self.root, 1)
        # 把任务卡 chapter_mode 改为 interior
        card_path = self.root / "01_大纲" / "章纲" / "第001章_task_card.json"
        card_data = json.loads(card_path.read_text(encoding="utf-8"))
        card_data["chapter_mode"] = "interior"
        card_path.write_text(json.dumps(card_data, ensure_ascii=False), encoding="utf-8")
        scenes = sync_scene_plan_from_task_card(self.root, 1)
        scene_dir = self.root / "02_正文" / "第001章_scenes"
        scene_dir.mkdir(parents=True)
        for scene in scenes:
            (scene_dir / f"scene_{scene.scene_number:03d}_draft_v001.md").write_text("场景正文", encoding="utf-8")
        (self.root / "02_正文" / "第001章_草稿.md").write_text("他坐着没动。", encoding="utf-8")
        for rel in ["审计", "读者镜像", "质量诊断"]:
            (self.root / "04_审核日志" / f"第001章_{rel}.md").write_text(f"# {rel}", encoding="utf-8")
        (self.root / "04_审核日志" / "第001章_质量诊断.json").write_text(
            json.dumps({"score": 92, "findings": []}, ensure_ascii=False), encoding="utf-8",
        )

        # interior 模式下：质量诊断完成 → 跳过 drama_diag，直接推 literary_critic
        self.assertEqual(chapter_flow(self.root, 1)["recommendation"]["action"], "literary_critic")
        # 步骤条里"戏剧"应该显示为已完成（其实是被模式跳过）
        steps = {step["name"]: step["done"] for step in chapter_flow(self.root, 1)["steps"]}
        self.assertTrue(steps.get("戏剧"))

    def test_recommendation_uses_quality_report_to_revise(self) -> None:
        outline = "# 第001章：雨夜\n\n## 核心事件\n收到信。"
        (self.root / "01_大纲" / "章纲" / "第001章.md").write_text(outline, encoding="utf-8")
        sync_task_card_from_outline(self.root, 1, outline)
        confirm_task_card(self.root, 1)
        scenes = sync_scene_plan_from_task_card(self.root, 1)
        scene_dir = self.root / "02_正文" / "第001章_scenes"
        scene_dir.mkdir(parents=True)
        for scene in scenes:
            (scene_dir / f"scene_{scene.scene_number:03d}_draft_v001.md").write_text("场景正文", encoding="utf-8")
        (self.root / "02_正文" / "第001章_草稿.md").write_text("他收到信。", encoding="utf-8")
        # 全部诊断环节都需要完成，AI 推进才会进入 feedback_revise
        for rel in [
            "审计", "AI味检查", "读者镜像", "深度检查",
            "质量诊断", "戏剧诊断", "文学批评", "风格法庭", "声音诊断", "编辑备忘录",
        ]:
            (self.root / "04_审核日志" / f"第001章_{rel}.md").write_text(f"# {rel}", encoding="utf-8")
        # 新语义：只有"硬伤"（forbidden 命中 / 任务卡核心未覆盖 / error 级）才推 feedback_revise，
        # 单纯低分或品味问题不再触发——避免模型为指标妥协人味。
        (self.root / "04_审核日志" / "第001章_质量诊断.json").write_text(
            json.dumps({
                "score": 60,
                "findings": [{"item": "触碰任务卡禁止事项", "level": "error", "detail": "提前揭露真相。"}],
                "task_card_alignment": {"forbidden_hits": ["提前揭露真相"]},
            }, ensure_ascii=False),
            encoding="utf-8",
        )

        flow = chapter_flow(self.root, 1)

        self.assertEqual(flow["recommendation"]["action"], "feedback_revise")

    def test_workspace_dashboard_picks_first_active_chapter(self) -> None:
        (self.root / "01_大纲" / "章纲" / "第001章.md").write_text("# 第001章：雨夜", encoding="utf-8")
        (self.root / "01_大纲" / "章纲" / "第002章.md").write_text("# 第002章：清晨", encoding="utf-8")

        dashboard = workspace_dashboard(self.root)

        self.assertEqual(dashboard["active_chapter"], 1)
        self.assertEqual(dashboard["totals"]["chapters"], 2)


class OnboardingStateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for rel in [
            "00_世界观/角色档案",
            "01_大纲/章纲",
            "02_正文",
            "03_滚动记忆",
            "05_项目管理",
        ]:
            (self.root / rel).mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _real(self, base: str, length: int = 220) -> str:
        return base + "正文内容用于通过最小字数门槛。" * length

    def test_stage_is_spec_when_template_still_has_placeholders(self) -> None:
        ensure_project_center(self.root)

        state = onboarding_state(self.root)

        self.assertEqual(state["stage"], "spec")
        self.assertFalse(state["completed"]["spec"])
        self.assertEqual(state["progress"], 0)
        self.assertIn("故事规格", state["next_step"])

    def test_stage_advances_to_world_after_spec_filled(self) -> None:
        self._write("05_项目管理/故事规格.md", self._real("# 故事规格\n\n主角是林望。"))

        state = onboarding_state(self.root)

        self.assertEqual(state["stage"], "world")
        self.assertTrue(state["completed"]["spec"])
        self.assertFalse(state["completed"]["world"])

    def test_stage_advances_to_outline_after_world_filled(self) -> None:
        self._write("05_项目管理/故事规格.md", self._real("# 故事规格\n\n主角是林望。"))
        self._write("00_世界观/世界观.md", self._real("# 世界观\n\n大陆分九州。"))

        state = onboarding_state(self.root)

        self.assertEqual(state["stage"], "outline")
        self.assertTrue(state["completed"]["world"])
        self.assertFalse(state["completed"]["outline"])

    def test_stage_requires_real_character_file_not_template(self) -> None:
        self._write("05_项目管理/故事规格.md", self._real("# 故事规格\n\n主角是林望。"))
        self._write("00_世界观/世界观.md", self._real("# 世界观\n\n大陆分九州。"))
        self._write("01_大纲/总纲.md", self._real("# 总纲\n\n第一卷夺剑。"))
        self._write("00_世界观/角色档案/角色模板.md", "# 模板")

        state = onboarding_state(self.root)

        self.assertEqual(state["stage"], "characters")
        self.assertFalse(state["completed"]["characters"])

    def test_stage_is_writing_when_first_chapter_outline_exists(self) -> None:
        self._write("05_项目管理/故事规格.md", self._real("# 故事规格\n\n主角是林望。"))
        self._write("00_世界观/世界观.md", self._real("# 世界观\n\n大陆分九州。"))
        self._write("01_大纲/总纲.md", self._real("# 总纲\n\n第一卷夺剑。"))
        self._write("00_世界观/角色档案/林望.md", "# 林望\n\n主角资料")
        self._write("01_大纲/章纲/第001章.md", "# 第001章：雨夜\n\n核心事件。")

        state = onboarding_state(self.root)

        self.assertEqual(state["stage"], "writing")
        self.assertEqual(state["progress"], 5)

    def test_dashboard_carries_onboarding_payload(self) -> None:
        ensure_project_center(self.root)

        dashboard = workspace_dashboard(self.root)

        self.assertIn("onboarding", dashboard)
        self.assertEqual(dashboard["onboarding"]["stage"], "spec")


class OnboardingV15Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for rel in [
            "00_世界观/角色档案",
            "01_大纲/卷纲",
            "01_大纲/章纲",
            "03_滚动记忆",
            "05_项目管理",
            "prompts",
        ]:
            (self.root / rel).mkdir(parents=True, exist_ok=True)
        for name in ["世界观生成.md", "总纲生成.md", "章纲生成.md", "角色批量生成.md"]:
            (self.root / "prompts" / name).write_text("请根据 {{ brief }} 生成。", encoding="utf-8")
        (self.root / "00_世界观" / "角色档案" / "角色模板.md").write_text("# 模板", encoding="utf-8")
        (self.root / "03_滚动记忆" / "最近摘要.md").write_text("# 最近摘要", encoding="utf-8")
        (self.root / "03_滚动记忆" / "伏笔追踪.md").write_text("", encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_story_spec_from_preset_has_no_placeholders(self) -> None:
        text = build_story_spec_from_preset("旧案幸存者收到雨夜来信。", "悬疑")

        self.assertIn("旧案幸存者", text)
        self.assertIn("类型：悬疑", text)
        self.assertNotIn("请在此填写", text)

    def test_generate_startup_package_writes_spec_and_ai_drafts(self) -> None:
        result = generate_startup_package(
            self.root,
            inspiration="旧案幸存者收到雨夜来信。",
            genre="悬疑",
            mock=True,
        )

        self.assertTrue(result["spec"].exists())
        self.assertGreaterEqual(len(result["drafts"]), 3)
        self.assertTrue(all(path.exists() for path in result["drafts"]))
        self.assertIn("旧案幸存者", result["spec"].read_text(encoding="utf-8"))

    def test_infer_and_adopt_worldbuilding_draft(self) -> None:
        draft_dir = self.root / "00_世界观" / "AI草案"
        draft_dir.mkdir(parents=True)
        draft = draft_dir / "世界观草案_20260101_010101.md"
        draft.write_text("# 世界观草案\n新世界。", encoding="utf-8")
        target = self.root / "00_世界观" / "世界观.md"
        target.write_text("旧世界。", encoding="utf-8")

        inferred = infer_adoption_target(self.root, draft)
        result = adopt_ai_draft(self.root, "00_世界观/AI草案/世界观草案_20260101_010101.md")

        self.assertEqual(inferred, target)
        self.assertEqual(target.read_text(encoding="utf-8"), "# 世界观草案\n新世界。")
        self.assertIsNotNone(result.backup)
        self.assertTrue(result.backup.exists())

    def test_infer_character_target_from_heading(self) -> None:
        draft_dir = self.root / "00_世界观" / "角色档案" / "AI草案"
        draft_dir.mkdir(parents=True)
        draft = draft_dir / "角色草案_20260101_010101.md"
        draft.write_text("# 角色档案：林渊\n\n## 基础信息", encoding="utf-8")

        target = infer_adoption_target(self.root, draft)

        self.assertEqual(target.name, "林渊.md")

    def test_character_target_ignores_project_alignment_heading(self) -> None:
        draft_dir = self.root / "00_世界观" / "角色档案" / "AI草案"
        draft_dir.mkdir(parents=True)
        draft = draft_dir / "郁时谌改稿_20260101_010101.md"
        draft.write_text(
            "### **项目规格对齐**\n\n说明。\n\n## 角色档案：郁时谌\n\n## 基础信息",
            encoding="utf-8",
        )

        target = infer_adoption_target(self.root, draft)

        self.assertEqual(target.name, "郁时谌.md")

    def test_delete_ai_draft_moves_only_draft_to_recycle_bin(self) -> None:
        draft_dir = self.root / "00_世界观" / "AI草案"
        draft_dir.mkdir(parents=True)
        draft = draft_dir / "世界观草案_20260101_010101.md"
        draft.write_text("# 世界观草案\n待删。", encoding="utf-8")

        result = delete_ai_draft(self.root, "00_世界观/AI草案/世界观草案_20260101_010101.md", "不采用")

        self.assertFalse(draft.exists())
        self.assertTrue(result.recycled.exists())
        self.assertIn("99_回收站", str(result.recycled))
        self.assertTrue(result.recycled.with_suffix(result.recycled.suffix + ".reason.txt").exists())

    def test_delete_ai_draft_rejects_non_draft_file(self) -> None:
        formal = self.root / "00_世界观" / "世界观.md"
        formal.write_text("# 正式世界观", encoding="utf-8")

        with self.assertRaises(ValueError):
            delete_ai_draft(self.root, "00_世界观/世界观.md")

    def test_list_ai_drafts_excludes_recycle_bin(self) -> None:
        active_dir = self.root / "00_世界观" / "AI草案"
        recycled_dir = self.root / "99_回收站" / "AI草案"
        active_dir.mkdir(parents=True)
        recycled_dir.mkdir(parents=True)
        (active_dir / "世界观草案_20260101_010101.md").write_text("# 活跃草案", encoding="utf-8")
        (recycled_dir / "世界观草案_20260101_010101_20260101_020202.md").write_text("# 已删草案", encoding="utf-8")

        rows = list_ai_drafts(self.root)

        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["source"].startswith("00_世界观/AI草案/"))

    def test_placeholder_fix_suggestions_return_questions(self) -> None:
        (self.root / "01_大纲" / "章纲" / "第001章.md").write_text("# 第001章：【章节标题】", encoding="utf-8")

        rows = placeholder_fix_suggestions(self.root)

        self.assertTrue(rows)
        self.assertIn("本章", rows[0]["question"])
        self.assertIn("雨夜来信", rows[0]["suggestion"])


class SpecTemplateUpgradeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_legacy_spec_is_upgraded_with_backup(self) -> None:
        from project_center import LEGACY_SPEC_TEMPLATES, SPEC_TEMPLATE, upgrade_legacy_spec

        spec_path = self.root / SPEC
        spec_path.parent.mkdir(parents=True, exist_ok=True)
        spec_path.write_text(LEGACY_SPEC_TEMPLATES[0] + "\n", encoding="utf-8")

        upgraded = upgrade_legacy_spec(self.root)

        self.assertTrue(upgraded)
        self.assertEqual(spec_path.read_text(encoding="utf-8"), SPEC_TEMPLATE.strip() + "\n")
        self.assertIn("一句话概括", spec_path.read_text(encoding="utf-8"))
        self.assertIn("（请在此填写）", spec_path.read_text(encoding="utf-8"))
        backups = list((spec_path.parent / "versions").glob("故事规格_*.md"))
        self.assertEqual(len(backups), 1)

    def test_user_edited_spec_is_not_overwritten(self) -> None:
        from project_center import upgrade_legacy_spec

        spec_path = self.root / SPEC
        spec_path.parent.mkdir(parents=True, exist_ok=True)
        spec_path.write_text("# 故事规格\n\n我已经写了自己的内容。\n", encoding="utf-8")

        upgraded = upgrade_legacy_spec(self.root)

        self.assertFalse(upgraded)
        self.assertIn("我已经写了自己的内容", spec_path.read_text(encoding="utf-8"))


class PlanningAssistTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for rel in [
            "00_世界观/角色档案",
            "01_大纲/卷纲",
            "01_大纲/章纲",
            "03_滚动记忆",
            "05_项目管理",
            "prompts",
        ]:
            (self.root / rel).mkdir(parents=True, exist_ok=True)
        (self.root / "00_世界观" / "世界观.md").write_text("# 世界观", encoding="utf-8")
        (self.root / "00_世界观" / "文风档案.md").write_text("# 文风", encoding="utf-8")
        (self.root / "00_世界观" / "角色档案" / "角色模板.md").write_text("# 角色档案：{{ name }}", encoding="utf-8")
        (self.root / "01_大纲" / "总纲.md").write_text("# 总纲", encoding="utf-8")
        (self.root / "01_大纲" / "章纲" / "第001章.md").write_text("# 第001章", encoding="utf-8")
        (self.root / "03_滚动记忆" / "最近摘要.md").write_text("", encoding="utf-8")
        (self.root / "03_滚动记忆" / "伏笔追踪.md").write_text("", encoding="utf-8")
        src_prompts = Path(__file__).resolve().parents[1] / "prompts"
        for name in ["世界观生成.md", "总纲生成.md", "卷纲生成.md", "角色生成.md", "角色批量生成.md", "章纲生成.md"]:
            (self.root / "prompts" / name).write_text((src_prompts / name).read_text(encoding="utf-8"), encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_planning_assist_writes_drafts_without_overwriting_sources(self) -> None:
        world_path = generate_worldbuilding_draft(self.root, "雨夜旧城", mock=True)
        outline_path = generate_outline_draft(self.root, "旧案主线", mock=True)
        char_path = generate_character_draft(self.root, "林渊", "调查者", mock=True)
        chapter_path = generate_chapter_outline_draft(self.root, 1, "来信", mock=True)
        volume_path = generate_volume_outline_draft(self.root, "第01卷.md", "立局", mock=True)

        self.assertIn("AI草案", str(world_path))
        self.assertIn("AI草案", str(outline_path))
        self.assertIn("AI草案", str(char_path))
        self.assertIn("AI草案", str(chapter_path))
        self.assertIn("AI草案", str(volume_path))
        self.assertEqual((self.root / "00_世界观" / "世界观.md").read_text(encoding="utf-8"), "# 世界观")
        self.assertEqual((self.root / "01_大纲" / "总纲.md").read_text(encoding="utf-8"), "# 总纲")

    def test_volume_outline_draft_adopts_back_to_volume_plan(self) -> None:
        (self.root / "01_大纲" / "卷纲" / "第01卷.md").write_text("# 第01卷：开局\n", encoding="utf-8")

        path = generate_volume_outline_draft(self.root, "第01卷.md", "卷末第一次越界", mock=True)
        target = infer_adoption_target(self.root, path)

        self.assertEqual(target.relative_to(self.root).as_posix(), "01_大纲/卷纲/第01卷.md")

    def test_planning_text_compaction_preserves_head_tail(self) -> None:
        text = "开头" + ("中段" * 3000) + "结尾"

        compacted = compact_planning_text(text, 1000, "总纲")

        self.assertLessEqual(len(compacted), 1000)
        self.assertIn("系统已压缩：总纲", compacted)
        self.assertTrue(compacted.startswith("开头"))
        self.assertTrue(compacted.endswith("结尾"))

    def test_outline_prompt_is_capped_before_model_call(self) -> None:
        huge_world = "世界观开头\n" + ("世界观中段\n" * 3000) + "世界观结尾"
        huge_outline = "总纲开头\n" + ("总纲中段\n" * 4000) + "总纲结尾"
        (self.root / "00_世界观" / "世界观.md").write_text(huge_world, encoding="utf-8")
        (self.root / "01_大纲" / "总纲.md").write_text(huge_outline, encoding="utf-8")

        class CaptureRouter:
            mode = "mock"

            def __init__(self, project_dir: Path):
                self.user_prompt = ""

            def assist_text(self, system_prompt: str, user_prompt: str, **kwargs) -> str:
                self.user_prompt = user_prompt
                return "# 总纲草案\n\n保留原始首尾信息。"

        captured = CaptureRouter(self.root)
        old_router = planning_assist.LLMRouter
        old_limit = os.environ.get("NOVEL_PLANNING_PROMPT_CHAR_LIMIT")
        planning_assist.LLMRouter = lambda project_dir: captured
        os.environ["NOVEL_PLANNING_PROMPT_CHAR_LIMIT"] = "12000"
        try:
            path = planning_assist.generate_outline_draft(self.root, "主线灵感", mock=True)
        finally:
            planning_assist.LLMRouter = old_router
            if old_limit is None:
                os.environ.pop("NOVEL_PLANNING_PROMPT_CHAR_LIMIT", None)
            else:
                os.environ["NOVEL_PLANNING_PROMPT_CHAR_LIMIT"] = old_limit

        self.assertTrue(path.exists())
        self.assertLessEqual(len(captured.user_prompt), 12000)
        self.assertIn("系统已压缩", captured.user_prompt)
        self.assertIn("当前辅助任务输入", captured.user_prompt)

    def test_outline_generation_continues_when_end_marker_missing(self) -> None:
        class ContinuingRouter:
            mode = "real"
            ASSIST_PROVIDER = "custom"
            CLAUDE_MAX_TOKENS = 8000
            DEEPSEEK_MAX_TOKENS = 32000

            def __init__(self, project_dir: Path):
                self.calls: list[str] = []

            def assist_text(self, system_prompt: str, user_prompt: str, **kwargs) -> str:
                self.calls.append(user_prompt)
                if len(self.calls) == 1:
                    return "# 总纲草案\n\n## 第一幕\n开端"
                return "## 第二幕\n后续\n\n[[END_OF_OUTLINE]]"

        router = ContinuingRouter(self.root)
        old_router = planning_assist.LLMRouter
        planning_assist.LLMRouter = lambda project_dir: router
        try:
            path = planning_assist.generate_outline_draft(self.root, "长篇总纲", mock=False)
        finally:
            planning_assist.LLMRouter = old_router

        content = path.read_text(encoding="utf-8")
        self.assertEqual(len(router.calls), 2)
        self.assertIn("从断点继续", router.calls[1])
        self.assertIn("第一幕", content)
        self.assertIn("第二幕", content)
        self.assertNotIn("[[END_OF_OUTLINE]]", content)

    def test_planning_prompt_includes_story_spec_context(self) -> None:
        from planning_assist import add_project_linkage

        (self.root / "05_项目管理" / "故事规格.md").write_text(
            "# 故事规格\n\n"
            "## 1. 一句话概括\n\n**回答**：旧案幸存者收到雨夜来信。\n\n"
            "## 2. 目标读者\n\n**回答**：喜欢冷读推理的读者。\n\n"
            "## 3. 核心冲突\n\n**回答**：追查旧案与保护亲人冲突。\n\n"
            "## 4. 主要角色\n\n**回答**：林渊。\n\n"
            "## 5. 类型与卖点\n\n**回答**：\n- 类型：悬疑\n- 卖点：证据链反转。\n\n"
            "## 6. 成功标准\n\n**回答**：每章都有线索推进。\n",
            encoding="utf-8",
        )

        prompt = add_project_linkage(self.root, "请生成世界观。", "world")

        self.assertIn("项目轴", prompt)
        self.assertIn("故事规格摘要", prompt)
        self.assertIn("旧案幸存者", prompt)
        self.assertIn("当前辅助任务输入", prompt)

    def test_worldbuilding_mock_reflects_story_spec_in_saved_draft(self) -> None:
        (self.root / "05_项目管理" / "故事规格.md").write_text(
            "# 故事规格\n\n"
            "## 1. 一句话概括\n\n**回答**：一个46岁在银行工作的中年男人（男主名：郁时谌）偶然接到来自未来的礼物，逆转人生。\n\n"
            "## 2. 目标读者\n\n**回答**：喜欢技术伦理、文明尺度和成年人情感关系的读者。\n\n"
            "## 3. 核心冲突\n\n**回答**：未来技术带来的逆袭欲望与社会代价冲突。\n\n"
            "## 4. 主要角色\n\n**回答**：郁时谌。\n\n"
            "## 5. 类型与卖点\n\n**回答**：\n- 类型：科幻、言情\n- 卖点：来自未来的礼物、全球科技进步。\n\n"
            "## 6. 成功标准\n\n**回答**：技术选择与情感选择互相牵动。\n",
            encoding="utf-8",
        )

        path = generate_worldbuilding_draft(self.root, "未来礼物", mock=True)
        content = path.read_text(encoding="utf-8")

        self.assertIn("项目规格对齐", content)
        self.assertIn("郁时谌", content)
        self.assertIn("未来礼物", content)
        self.assertIn("科幻、言情", content)

    def test_character_batch_assist_splits_into_multiple_drafts(self) -> None:
        paths = generate_character_batch_drafts(self.root, count=4, brief="围绕旧案生成群像", mock=True)

        self.assertEqual(len(paths), 4)
        self.assertTrue(all("AI草案" in str(path) for path in paths))
        self.assertTrue(any("林渊" in path.read_text(encoding="utf-8") for path in paths))
        targets = [infer_adoption_target(self.root, path).name for path in paths]
        self.assertEqual(len(set(targets)), 4)
        self.assertTrue(all(name.endswith(".md") and "批量" not in name for name in targets))

    def test_split_character_batch_by_heading(self) -> None:
        blocks = split_character_batch("# 角色档案：甲\n内容\n\n# 角色档案：乙\n内容")

        self.assertEqual([name for name, _ in blocks], ["甲", "乙"])

    def test_split_character_batch_accepts_loose_headings(self) -> None:
        blocks = split_character_batch("## 角色档案：甲\n内容\n\n### 角色：乙\n内容")

        self.assertEqual([name for name, _ in blocks], ["甲", "乙"])
        self.assertTrue(all(block.startswith("# 角色档案：") for _, block in blocks))

    def test_parse_review_report_extracts_issues(self) -> None:
        audit = """- 【问题位置】文本中仍有占位符。
  【冲突依据】占位符会导致模型补设定。
  【修改建议】补完章纲。
"""
        report = parse_review_report(1, audit, "mock-critic", "audit.md")

        self.assertEqual(report.chapter_number, 1)
        self.assertEqual(len(report.issues), 1)
        self.assertIn("占位符", report.issues[0].location)

    def test_parse_foreshadow_table(self) -> None:
        table = """| 编号 | 埋入章节 | 伏笔内容 | 状态 | 计划回收章节 |
|------|---------|---------|------|------------|
| F001 | 第001章 | 照片日期异常 | 🟡待回收 | 第017章 |
"""
        items = parse_foreshadow_table(table)

        self.assertEqual(items[0].id, "F001")
        self.assertEqual(items[0].status, "pending")

    def test_write_memory_json_validates_schema(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = write_memory_json(Path(tmp), 1, "# 第001章：雨夜\n正文", "- 核心事件：收到信")
            self.assertTrue(path.exists())
            self.assertIn('"chapter_number": 1', path.read_text(encoding="utf-8"))


class PromptAssemblyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for rel in [
            "00_世界观/角色档案",
            "01_大纲/章纲",
            "02_正文",
            "03_滚动记忆",
            "04_审核日志",
            "05_项目管理",
            "prompts",
        ]:
            (self.root / rel).mkdir(parents=True, exist_ok=True)
        # 拷贝项目内的真实 prose 模板，确保占位符替换路径与生产一致
        template_src = Path(__file__).resolve().parent.parent / "prompts" / "正文生成.md"
        (self.root / "prompts" / "正文生成.md").write_text(
            template_src.read_text(encoding="utf-8"), encoding="utf-8"
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _filled_spec(self) -> str:
        return (
            "# 故事规格\n\n"
            "## 1. 一句话概括\n\n"
            "**回答**：被门派除名的废柴弟子觉醒上古剑魂，必须夺回母亲留下的剑。\n\n"
            "## 2. 目标读者\n\n"
            "**回答**：25-35 岁，男性向，偏好爽文快节奏。\n\n"
            "## 3. 核心冲突\n\n"
            "**回答**：\n- 主冲突：人 vs 命运（夺剑还魂）。\n- 次冲突：人 vs 自己（恨过母亲）。\n\n"
            "## 4. 主要角色\n\n"
            "**回答**：\n- 主角：林望。\n- 反派：太上长老。\n\n"
            "## 5. 类型与卖点\n\n"
            "**回答**：\n- 类型：玄幻/仙侠。\n- 卖点：反差人设 + 高密度燃点。\n\n"
            "## 6. 成功标准\n\n"
            "**回答**：稳定日更 3000 字。\n"
        )

    def test_render_prose_system_prompt_strips_all_placeholders(self) -> None:
        from prompt_assembly import render_prose_system_prompt

        self._write("05_项目管理/创作宪法.md", "# 创作宪法\n- 不输出占位符。")
        self._write("05_项目管理/故事规格.md", self._filled_spec())
        self._write("00_世界观/文风档案.md", "# 文风档案\n- 短句优先。")

        rendered = render_prose_system_prompt(self.root)

        self.assertNotIn("{{", rendered)
        self.assertNotIn("在此填写", rendered)
        self.assertNotIn("请替换", rendered)
        self.assertIn("玄幻", rendered)
        self.assertIn("不输出占位符", rendered)

    def test_render_prose_system_prompt_uses_fallbacks_when_files_missing(self) -> None:
        from prompt_assembly import render_prose_system_prompt

        rendered = render_prose_system_prompt(self.root)

        self.assertNotIn("{{", rendered)
        self.assertNotIn("在此填写", rendered)
        self.assertIn("通用中文小说", rendered)
        self.assertIn("项目宪法尚未填写", rendered)

    def test_seed_style_library_injects_three_samples(self) -> None:
        from prompt_assembly import inject_prose_samples, _load_seed_library

        seeds = _load_seed_library(self.root)
        samples = inject_prose_samples(self.root, current_chapter_num=1)

        self.assertGreaterEqual(len(seeds), 8)
        self.assertEqual(samples.count(">>>"), 3)
        self.assertIn("来自种子库·技巧", samples)
        self.assertIn("身体动作代替情绪词", samples)

    def test_style_profile_samples_are_used_when_profile_selected(self) -> None:
        from prompt_assembly import inject_prose_samples

        samples = inject_prose_samples(
            self.root,
            current_chapter_num=1,
            style_profile_name="wang_xiaobo",
        )

        self.assertIn("来自王小波路线", samples)
        self.assertIn("逻辑折叠", samples)
        self.assertEqual(samples.count(">>>"), 3)

    def test_custom_style_profile_can_be_project_default(self) -> None:
        from style_profiles import StyleProfile, read_project_style_profile_name, resolve_style_profile_name, save_user_profile

        save_user_profile(
            self.root,
            StyleProfile(
                name="my_voice",
                display_name="我的文风",
                personality_summary="短句，动作压住情绪。",
            ),
        )
        self._write(".env", "NOVEL_STYLE_PROFILE=my_voice\n")

        self.assertEqual(read_project_style_profile_name(self.root), "my_voice")
        self.assertEqual(resolve_style_profile_name(self.root), "my_voice")

    def test_prose_prompt_includes_chapter_mode_and_style_profile(self) -> None:
        from prompt_assembly import render_prose_system_prompt
        from novel_schemas import model_to_json

        (self.root / "01_大纲" / "章纲").mkdir(parents=True, exist_ok=True)
        self._write(
            "01_大纲/章纲/第001章_task_card.json",
            model_to_json(
                ChapterTaskCard(
                    chapter_number=1,
                    chapter_mode="interior",
                    ending_style="open",
                    pacing="slow_burn",
                    style_profile="yu_hua",
                )
            ),
        )

        rendered = render_prose_system_prompt(self.root, 1)

        self.assertIn("本章模式写作规则", rendered)
        self.assertIn("ChapterMode：interior", rendered)
        self.assertIn("余华路线", rendered)

    def test_user_style_samples_take_priority_over_seed_samples(self) -> None:
        from prompt_assembly import inject_prose_samples

        self._write(
            "00_世界观/文风档案.md",
            "\n".join([
                "# 文风档案",
                "## 参考段落 A",
                "```",
                "她把银行卡推回去，卡角撞到杯底，发出很轻的一声。郁时谌没有接，只看着那串被水汽糊住的号码。她说：“这不是钱的问题。”窗外的雨正好停了，屋里反而更静。",
                "```",
                "**我喜欢这里的**：动作压住情绪，靠物件和停顿写关系变化。",
            ]),
        )

        samples = inject_prose_samples(self.root, current_chapter_num=1)

        self.assertTrue(samples.startswith("样本 1（来自文风档案"))
        self.assertIn("银行卡推回去", samples)
        self.assertIn("动作压住情绪", samples)

    def test_finalized_chapter_samples_are_used_after_chapter_three(self) -> None:
        from prompt_assembly import inject_prose_samples

        paragraph = (
            "郁时谌把检测报告压在掌心下面，纸边被他按出一道浅浅的弯。"
            "沈逐光没有催，只把电脑屏幕转过去，让那条异常曲线停在他眼前。"
            "“你现在还有两个选择。”她说，“承认它来自未来，或者继续骗我它是巧合。”"
        )
        self._write("02_正文/第003章_定稿.md", f"# 第003章\n\n{paragraph}\n")

        samples = inject_prose_samples(self.root, current_chapter_num=4)

        self.assertIn("第003章定稿片段", samples)
        self.assertIn("异常曲线", samples)

    def test_high_cinematic_finalized_samples_beat_mock_diagnostics(self) -> None:
        from prompt_assembly import inject_prose_samples

        mock_paragraph = (
            "他推门进去时，会议室里的人同时抬头。投影幕还亮着，数据停在一条夸张的斜线上。"
            "“你们不用等我解释。”他说，“这份东西本来就不该出现在这里。”"
        )
        strong_paragraph = (
            "沈逐光把手套摘下来，指节上全是压痕。烧杯里的液体还在冒细泡，她却先关掉了排风。"
            "“你听。”她说。机器的蜂鸣停了，实验室里只剩那块金属片轻轻裂开的声音。"
            "郁时谌没有说话，只把录音笔往前推了半寸。"
        )
        self._write("02_正文/第002章_定稿.md", f"# 第002章\n\n{mock_paragraph}\n")
        self._write("02_正文/第003章_定稿.md", f"# 第003章\n\n{strong_paragraph}\n")
        self._write("04_审核日志/第002章_戏剧诊断.json", '{"cinematic_score": 99, "is_mock": true}')
        self._write("04_审核日志/第003章_戏剧诊断.json", '{"cinematic_score": 88, "is_mock": false}')

        samples = inject_prose_samples(self.root, current_chapter_num=6)

        self.assertIn("第003章高画面感片段", samples)
        self.assertIn("金属片轻轻裂开", samples)
        self.assertNotIn("第002章", samples)

    def test_parse_story_spec_extracts_filled_answers(self) -> None:
        from prompt_assembly import parse_story_spec

        self._write("05_项目管理/故事规格.md", self._filled_spec())

        spec = parse_story_spec(self.root)

        self.assertIn("林望", spec["main_characters"])
        self.assertIn("玄幻", spec["selling_points"])
        self.assertIn("命运", spec["core_conflict"])
        self.assertIn("男性向", spec["audience"])

    def test_parse_story_spec_returns_empty_for_unfilled_template(self) -> None:
        from project_center import SPEC_TEMPLATE
        from prompt_assembly import parse_story_spec

        self._write("05_项目管理/故事规格.md", SPEC_TEMPLATE)

        spec = parse_story_spec(self.root)

        # 全部字段在新模板下都应被识别为未填（全是"（请在此填写）"）
        for key, value in spec.items():
            self.assertEqual(value, "", f"{key} 应识别为空，实际：{value!r}")

    def test_axis_context_includes_constitution_spec_style_and_outline(self) -> None:
        from prompt_assembly import build_axis_context

        self._write("05_项目管理/创作宪法.md", "# 创作宪法\n- 红线 A。")
        self._write("05_项目管理/故事规格.md", self._filled_spec())
        self._write("00_世界观/文风档案.md", "# 文风档案\n- 短句优先。")
        self._write("01_大纲/总纲.md", "# 总纲\n第一卷夺剑还魂。")
        self._write("01_大纲/卷纲/第01卷.md", "# 第01卷：夺剑\n\n- 章节范围：001-050\n- 叙事功能：夺回母剑。")

        axis = build_axis_context(self.root)

        self.assertIn("创作宪法", axis)
        self.assertIn("红线 A", axis)
        self.assertIn("故事规格摘要", axis)
        self.assertIn("林望", axis)
        self.assertIn("文风档案", axis)
        self.assertIn("短句优先", axis)
        self.assertIn("全书总纲", axis)
        self.assertIn("夺剑还魂", axis)
        self.assertIn("卷/幕结构", axis)
        self.assertIn("夺回母剑", axis)

    def test_axis_context_includes_local_consistency_warnings(self) -> None:
        from prompt_assembly import build_axis_context

        self._write(
            "05_项目管理/故事规格.md",
            "# 故事规格\n\n## 4. 主要角色\n\n**回答**：\n- 反派/对手：待命名 · 掌握关键资源的人",
        )
        self._write("01_大纲/总纲.md", "# 总纲\n\n| 反派·韩既白 | 旧秩序维护者 |")

        axis = build_axis_context(self.root)

        self.assertIn("本地一致性预警", axis)
        self.assertIn("故事规格主要角色位", axis)
        self.assertIn("韩既白", axis)

    def test_axis_context_skips_missing_or_empty_files(self) -> None:
        from prompt_assembly import build_axis_context

        self._write("05_项目管理/故事规格.md", self._filled_spec())

        axis = build_axis_context(self.root)

        self.assertIn("故事规格摘要", axis)
        self.assertNotIn("创作宪法（红线）", axis)
        self.assertNotIn("文风档案", axis)
        self.assertNotIn("全书总纲", axis)

    def test_planning_context_links_story_spec_to_world_and_characters(self) -> None:
        from prompt_assembly import build_linkage_report, build_planning_context

        self._write("05_项目管理/故事规格.md", self._filled_spec())
        self._write("05_项目管理/创作宪法.md", "# 创作宪法\n- 不违背故事规格。")
        self._write("00_世界观/文风档案.md", "# 文风档案\n- 句子短，动作具体。")
        self._write("01_大纲/总纲.md", "# 总纲\n第一卷围绕夺剑还魂展开。")
        self._write("01_大纲/卷纲/第01卷.md", "# 第01卷：夺剑\n\n- 章节范围：001-050\n- 叙事功能：主角夺剑。")
        self._write("00_世界观/世界观.md", "# 世界观\n门派以剑魂血契统治。")
        self._write("00_世界观/角色档案/林望.md", "# 角色档案：林望\n- 目标：夺剑还魂。")

        world_ctx = build_planning_context(self.root, target="world")
        char_ctx = build_planning_context(self.root, target="character")
        report = build_linkage_report(self.root)

        self.assertIn("故事规格摘要", world_ctx)
        self.assertIn("夺剑还魂", world_ctx)
        self.assertIn("已有世界观", char_ctx)
        self.assertIn("已有角色档案索引", char_ctx)
        self.assertIn("世界观 AI 辅助", report["consumers"][0]["模块"])
        self.assertEqual(report["consumers"][0]["状态"], "已联动")
        modules = [row["模块"] for row in report["consumers"]]
        self.assertIn("AI味检查/文风检查", modules)
        self.assertIn("人物状态维护", modules)
        self.assertTrue(any("卷/幕结构" in row["使用信息"] for row in report["consumers"]))

    def test_build_chapter_context_combines_axis_rolling_and_rag(self) -> None:
        from prompt_assembly import build_chapter_context

        self._write("05_项目管理/创作宪法.md", "# 创作宪法\n- 红线 A。")
        self._write("03_滚动记忆/最近摘要.md", "# 最近摘要\n## 第001章\n收到信。")
        self._write("01_大纲/卷纲/第01卷.md", "# 第01卷：开局\n\n- 章节范围：001-050\n- 叙事功能：建立未来礼物规则。")

        class _StubRAG:
            def build_context(self, _: str) -> str:
                return "## 相关世界设定\n\n世界设定 X。"

        ctx = build_chapter_context(self.root, _StubRAG(), "# 第002章：清晨")

        self.assertIn("红线 A", ctx)
        self.assertIn("最近章节摘要", ctx)
        self.assertIn("收到信", ctx)
        self.assertIn("世界设定 X", ctx)
        self.assertIn("当前卷/幕约束", ctx)
        self.assertIn("未来礼物规则", ctx)

    def test_render_task_card_block_includes_forbidden_and_foreshadow(self) -> None:
        from prompt_assembly import render_task_card_block
        from structured_store import (
            confirm_task_card,
            sync_task_card_from_outline,
        )

        outline = (
            "# 第001章：雨夜\n\n"
            "## 基本信息\n- 视角人物：林望\n- 字数目标：3000-4000\n- 时间线：故事第3天，深夜\n\n"
            "## 核心事件\n收到信，被迫出门。\n\n"
            "## 情感弧线\n警觉—压抑—决意。\n\n"
            "## 伏笔操作\n- 埋下：照片日期异常\n- 收回：无\n\n"
            "## 章末悬念\n门外敲门。\n\n"
            "## 禁止事项\n- 不得出现内心独白超过两段\n- 不得提到下章反派身份\n"
        )
        self._write("01_大纲/章纲/第001章.md", outline)
        sync_task_card_from_outline(self.root, 1, outline)
        confirm_task_card(self.root, 1)

        block = render_task_card_block(self.root, 1)

        self.assertIn("本章结构化任务卡", block)
        self.assertIn("林望", block)
        self.assertIn("禁止事项", block)
        self.assertIn("内心独白", block)
        self.assertIn("照片日期异常", block)
        self.assertIn("门外敲门", block)

    def test_render_task_card_block_returns_empty_when_no_card(self) -> None:
        from prompt_assembly import render_task_card_block

        self.assertEqual(render_task_card_block(self.root, 99), "")

    def test_generate_chapter_payload_contains_task_card_and_axis(self) -> None:
        """端到端：mock 模式下，组装好的 system + context + task_card 都进入 LLM 调用 hash。"""
        from llm_router import LLMRouter
        from prompt_assembly import (
            build_chapter_context,
            render_prose_system_prompt,
            render_task_card_block,
        )
        from structured_store import confirm_task_card, sync_task_card_from_outline

        self._write("05_项目管理/创作宪法.md", "# 创作宪法\n- 不输出占位符。")
        self._write("05_项目管理/故事规格.md", self._filled_spec())
        self._write("00_世界观/文风档案.md", "# 文风档案\n- 短句优先。")
        self._write("01_大纲/总纲.md", "# 总纲\n第一卷夺剑还魂。")

        outline = (
            "# 第001章：雨夜\n\n"
            "## 基本信息\n- 视角人物：林望\n- 字数目标：3000\n\n"
            "## 核心事件\n收到信。\n\n"
            "## 章末悬念\n门外敲门。\n\n"
            "## 禁止事项\n- 不得提反派身份\n"
        )
        self._write("01_大纲/章纲/第001章.md", outline)
        sync_task_card_from_outline(self.root, 1, outline)
        confirm_task_card(self.root, 1)

        system_prompt = render_prose_system_prompt(self.root)
        ctx = build_chapter_context(self.root, None, outline)
        task_card_block = render_task_card_block(self.root, 1)

        # 关键：拼装结果必须能检验三块都在
        self.assertIn("玄幻", system_prompt)
        self.assertIn("不输出占位符", ctx)
        self.assertIn("夺剑还魂", ctx)
        self.assertIn("不得提反派身份", task_card_block)

        # 走一次 mock 调用，确保接口签名兼容
        router = LLMRouter(mode="mock", project_dir=str(self.root))
        composed = router._compose_chapter_user_msg(ctx, outline, task_card_block)
        self.assertIn("夺剑还魂", composed)
        self.assertIn("本章结构化任务卡", composed)
        self.assertIn("不得提反派身份", composed)


# ── V4.0 Phase D 场景诊断测试 ──────────────────────────────────────────────────


class SceneDiagnosticTests(unittest.TestCase):
    """_diagnose_scene_locally() chun gui ze zhen duan。"""

    def setUp(self):
        from novel_pipeline import _diagnose_scene_locally
        self.fn = _diagnose_scene_locally

    def test_conflict_visible_with_choice_and_cost(self):
        text = "他犹豫了片刻，要么说出真相付出代价，要么永远失去她的信任。"
        result = self.fn(1, 1, text)
        self.assertTrue(result["conflict_visible"])

    def test_conflict_not_visible_without_patterns(self):
        text = "阳光很好，微风拂过窗帘。她坐在窗边喝茶，看着窗外的花。"
        result = self.fn(1, 1, text)
        self.assertFalse(result["conflict_visible"])

    def test_body_action_density_computed(self):
        text = "他站起身走向门口伸手推开门跨出去回头看了一眼然后走了。"
        result = self.fn(1, 1, text)
        self.assertGreater(result["body_action_density"], 0)
        self.assertLessEqual(result["body_action_density"], 100)

    def test_body_action_zero_density_on_empty(self):
        result = self.fn(1, 1, "")
        self.assertEqual(result["body_action_density"], 0.0)

    def test_dialogue_advances_with_question(self):
        text = "她问：" + chr(0x201C) + "你知道真相吗？" + chr(0x201D)
        result = self.fn(1, 1, text)
        self.assertTrue(result["dialogue_advances"])

    def test_dialogue_not_advances_with_banal(self):
        text = "他说：" + chr(0x201C) + "好的。" + chr(0x201D)
        result = self.fn(1, 1, text)
        self.assertFalse(result["dialogue_advances"])

    def test_no_dialogue_defaults_to_true(self):
        """无对白场景不因对白扣分。"""
        text = "他在房间里来回踱步，拳头紧握，一言不发。"
        result = self.fn(1, 1, text)
        self.assertTrue(result["dialogue_advances"])

    def test_score_in_range(self):
        texts = [
            "阳光很好。",  # low
            "他要么走要么留，这选择让他付出一切。",  # mid with conflict
            "他站起身，推开门，要么说出秘密要么死。她问：" + chr(0x201C) + "你到底知道什么？" + chr(0x201D),  # good
        ]
        for text in texts:
            with self.subTest(text=text[:30]):
                result = self.fn(1, 1, text)
                self.assertGreaterEqual(result["score"], 0)
                self.assertLessEqual(result["score"], 10)

    def test_diagnostic_returns_all_required_keys(self):
        result = self.fn(2, 3, "测试正文")
        for key in ["chapter_number", "scene_number", "conflict_visible",
                     "body_action_density", "dialogue_advances", "notes", "score"]:
            self.assertIn(key, result)

    def test_diagnostic_model_roundtrip(self):
        from novel_schemas import SceneDiagnosticNote
        result = self.fn(1, 2, "他要么留下要么走。")
        model = SceneDiagnosticNote(**result)
        data = json.loads(model.model_dump_json())
        self.assertEqual(data["chapter_number"], 1)
        self.assertEqual(data["scene_number"], 2)
        self.assertIn(data["score"], range(11))


class ScenePlanDiagnosticFieldsTests(unittest.TestCase):
    """ScenePlan diagnostic_score / diagnostic_notes zi duan。"""

    def test_scene_plan_has_diagnostic_fields(self):
        from novel_schemas import ScenePlan
        sp = ScenePlan(chapter_number=1, scene_number=1)
        self.assertIsNone(sp.diagnostic_score)
        self.assertEqual(sp.diagnostic_notes, [])

    def test_diagnostic_fields_serialize(self):
        from novel_schemas import ScenePlan
        sp = ScenePlan(
            chapter_number=1, scene_number=2,
            diagnostic_score=7,
            diagnostic_notes=["对白推进不足"],
        )
        data = json.loads(sp.model_dump_json())
        self.assertEqual(data["diagnostic_score"], 7)
        self.assertEqual(data["diagnostic_notes"], ["对白推进不足"])


if __name__ == "__main__":
    unittest.main()
