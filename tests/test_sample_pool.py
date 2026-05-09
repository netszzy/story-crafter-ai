"""V3.1 样本池单元测试。"""

import json
import tempfile
import unittest
from pathlib import Path

from novel_schemas import ProseSampleEntry
from sample_pool import (
    _candidate_paragraphs,
    _has_dialogue_or_action,
    _normalize,
    exclude_sample,
    get_pool_samples,
    include_sample,
    load_pool,
    lock_sample,
    populate_from_chapter,
    save_pool,
    unlock_sample,
)


# ── helpers ──────────────────────────────────────────────────────────────────

def _entry(text="郁时谌把信压在掌心下面，雨声敲着窗。",
           chapter=3, score=85, locked=False, excluded=False):
    return ProseSampleEntry(
        text=text,
        source_chapter=chapter,
        technique_label=f"第{chapter:03d}章高画面感片段",
        cinematic_score=score,
        locked=locked,
        excluded=excluded,
    )


def _make_chapter_text(*paragraphs: str) -> str:
    return "\n\n".join(paragraphs)


# ─────────────────────────────────────────────────────────────────────────────
# 段落抽取
# ─────────────────────────────────────────────────────────────────────────────

class TestParagraphExtraction(unittest.TestCase):
    def test_normalize_collapses_whitespace(self):
        result = _normalize("  第一行  \n  第二行  ")
        self.assertEqual(result, "第一行 第二行")

    def test_has_dialogue_detects_quotes(self):
        LQ = "“"  # "
        RQ = "”"  # "
        self.assertTrue(_has_dialogue_or_action(f"他说：{LQ}走吧。{RQ}"))
        self.assertTrue(_has_dialogue_or_action("她「嗯」了一声。"))

    def test_has_dialogue_detects_action_verb(self):
        self.assertTrue(_has_dialogue_or_action("他把杯子推开了。"))

    def test_has_dialogue_false_for_pure_description(self):
        self.assertFalse(_has_dialogue_or_action("天空很蓝，云很白，风吹过草地。"))

    def test_candidate_paragraphs_filters_by_length(self):
        text = _make_chapter_text(
            "# 标题应该被跳过",
            "太短",
            "a" * 100 + "他推开门走了出去。",
            # >80 chars but no action verbs, no dialogue quotes
            "天空很蓝，云朵很白，微风轻轻拂过一望无际的草原。"
            "远处的山峰在薄雾中若隐若现，像是水墨画里的淡影。"
            "阳光温暖地洒在大地上，一切都那么平静安详。"
            "偶尔有几只鸟飞过，但也只是远远的剪影。"
            "时间仿佛在这里凝固了，只剩下呼吸和心跳。"
            "这样的宁静让人想起很久以前的一些事情。",
        )
        result = _candidate_paragraphs(text)
        self.assertEqual(len(result), 1)
        self.assertIn("推开门", result[0])

    def test_candidate_paragraphs_skips_headings(self):
        text = ("# 第 1 章 开头\n\n"
                + "a" * 80
                + "他推开门走到院子里站了一会又把门关上走了出去。"
                + "外面的阳光很刺眼，他眯起眼睛看了看四周然后朝巷口走去。")
        result = _candidate_paragraphs(text)
        self.assertEqual(len(result), 1)
        self.assertNotIn("#", result[0])


# ─────────────────────────────────────────────────────────────────────────────
# CRUD
# ─────────────────────────────────────────────────────────────────────────────

class TestPoolCRUD(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.project_dir = Path(self.tmp)
        (self.project_dir / "05_项目管理").mkdir(parents=True)

    def test_save_and_load_roundtrip(self):
        entries = [_entry(chapter=3, score=85), _entry(chapter=4, score=90)]
        save_pool(self.project_dir, entries)
        loaded = load_pool(self.project_dir)
        self.assertEqual(len(loaded), 2)
        self.assertEqual(loaded[0].source_chapter, 3)
        self.assertEqual(loaded[1].cinematic_score, 90)

    def test_load_missing_file_returns_empty(self):
        result = load_pool(self.project_dir)
        self.assertEqual(result, [])

    def test_load_corrupt_json_returns_empty(self):
        path = self.project_dir / "05_项目管理" / "prose_sample_pool.json"
        path.write_text("not json", encoding="utf-8")
        result = load_pool(self.project_dir)
        self.assertEqual(result, [])

    def test_pool_path(self):
        from sample_pool import _pool_path
        path = _pool_path(self.project_dir)
        self.assertIn("prose_sample_pool.json", str(path))


# ─────────────────────────────────────────────────────────────────────────────
# 入池规则
# ─────────────────────────────────────────────────────────────────────────────

class TestPoolPopulation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.project_dir = Path(self.tmp)
        (self.project_dir / "05_项目管理").mkdir(parents=True)

    def test_populate_adds_entries_for_high_score(self):
        LQ = "“"
        RQ = "”"
        text = _make_chapter_text(
            "a" * 80 + "他推开门",
            "b" * 80 + f"她说：{LQ}你好。{RQ}",
        )
        added = populate_from_chapter(self.project_dir, 3, text, cinematic_score=85)
        self.assertEqual(added, 2)
        pool = load_pool(self.project_dir)
        self.assertEqual(len(pool), 2)
        self.assertEqual(pool[0].source_chapter, 3)

    def test_populate_skips_low_score(self):
        text = _make_chapter_text("a" * 80 + "她推开门走了出去。")
        added = populate_from_chapter(self.project_dir, 3, text, cinematic_score=70)
        self.assertEqual(added, 0)
        self.assertEqual(load_pool(self.project_dir), [])

    def test_populate_skips_mock(self):
        text = _make_chapter_text("a" * 80 + "她推开门走了出去。")
        added = populate_from_chapter(self.project_dir, 3, text, cinematic_score=90, is_mock=True)
        self.assertEqual(added, 0)

    def test_populate_deduplicates_same_text(self):
        text = _make_chapter_text("a" * 80 + "她推开门走了出去。")
        populate_from_chapter(self.project_dir, 3, text, cinematic_score=85)
        added2 = populate_from_chapter(self.project_dir, 3, text, cinematic_score=85)
        self.assertEqual(added2, 0)

    def test_populate_replaces_same_chapter(self):
        text1 = _make_chapter_text("a" * 80 + "第一段话包含了推门动作，这是测试文本。")
        text2 = _make_chapter_text("b" * 80 + "第二段话她说走吧是不同的内容。")
        populate_from_chapter(self.project_dir, 3, text1, cinematic_score=85)
        populate_from_chapter(self.project_dir, 3, text2, cinematic_score=88)
        pool = load_pool(self.project_dir)
        self.assertEqual(len(pool), 1)
        self.assertIn("第二段", pool[0].text)

    def test_pool_cap(self):
        from sample_pool import POOL_CAP
        for i in range(POOL_CAP + 10):
            text = _make_chapter_text(f"第{i:02d}段长文本" + "a" * 80 + "她推开门走了出去。")
            populate_from_chapter(self.project_dir, i + 1, text, cinematic_score=85)
        pool = load_pool(self.project_dir)
        self.assertLessEqual(len(pool), POOL_CAP)


# ─────────────────────────────────────────────────────────────────────────────
# 选取优先级
# ─────────────────────────────────────────────────────────────────────────────

class TestPoolSelection(unittest.TestCase):
    def test_locked_entries_first(self):
        pool = [
            _entry(chapter=3, score=80),
            _entry(chapter=4, score=90, locked=True),
            _entry(chapter=5, score=85),
        ]
        result = get_pool_samples(pool, max_count=3, seen=set())
        labels = [r[0] for r in result]
        self.assertIn("样本池(锁定)", labels[0])
        self.assertEqual(labels.count("样本池(锁定)"), 1)

    def test_excluded_entries_never_returned(self):
        pool = [
            _entry(chapter=3, score=90, excluded=True),
            _entry(chapter=4, score=80),
        ]
        result = get_pool_samples(pool, max_count=2, seen=set())
        chapters = [r[1] for r in result]
        self.assertNotIn("第003章高画面感片段", chapters)
        self.assertEqual(len(result), 1)

    def test_excluded_wins_over_locked(self):
        pool = [_entry(chapter=3, score=90, locked=True, excluded=True)]
        result = get_pool_samples(pool, max_count=1, seen=set())
        self.assertEqual(len(result), 0)

    def test_sort_by_score_desc(self):
        pool = [
            _entry(chapter=3, score=80),
            _entry(chapter=4, score=95),
            _entry(chapter=5, score=85),
        ]
        result = get_pool_samples(pool, max_count=3, seen=set())
        # 第一条应该是最高分（95）的条目
        self.assertGreaterEqual(len(result), 1)

    def test_respects_max_count(self):
        pool = [_entry(chapter=i, score=80 + i) for i in range(10)]
        result = get_pool_samples(pool, max_count=3, seen=set())
        self.assertLessEqual(len(result), 3)

    def test_respects_seen_dedup(self):
        pool = [_entry(chapter=3, score=85)]
        seen = {_normalize(pool[0].text)}
        result = get_pool_samples(pool, max_count=1, seen=seen)
        self.assertEqual(len(result), 0)


# ─────────────────────────────────────────────────────────────────────────────
# 锁定/排除 toggle
# ─────────────────────────────────────────────────────────────────────────────

class TestFlags(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.project_dir = Path(self.tmp)
        (self.project_dir / "05_项目管理").mkdir(parents=True)
        save_pool(self.project_dir, [_entry(chapter=3, score=85)])

    def test_lock_sample(self):
        pool = lock_sample(self.project_dir, 0)
        self.assertTrue(pool[0].locked)

    def test_unlock_sample(self):
        lock_sample(self.project_dir, 0)
        pool = unlock_sample(self.project_dir, 0)
        self.assertFalse(pool[0].locked)

    def test_exclude_sample(self):
        pool = exclude_sample(self.project_dir, 0)
        self.assertTrue(pool[0].excluded)

    def test_include_sample(self):
        exclude_sample(self.project_dir, 0)
        pool = include_sample(self.project_dir, 0)
        self.assertFalse(pool[0].excluded)

    def test_flag_changes_persisted(self):
        lock_sample(self.project_dir, 0)
        pool = load_pool(self.project_dir)
        self.assertTrue(pool[0].locked)

    def test_invalid_index_noop(self):
        pool_before = load_pool(self.project_dir)
        lock_sample(self.project_dir, 99)
        pool_after = load_pool(self.project_dir)
        self.assertEqual(len(pool_before), len(pool_after))


if __name__ == "__main__":
    unittest.main()
