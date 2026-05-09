"""
V3.1 跨章节戏剧诊断趋势测试。
"""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from dramatic_arc_diagnostics import compute_drama_trends
from novel_schemas import ChapterDramaSnapshot, DramaTrends


class TestDramaTrendsEmpty(unittest.TestCase):
    def test_empty_directory_returns_insufficient_data(self):
        with TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            (project_dir / "04_审核日志").mkdir()
            trends = compute_drama_trends(project_dir)
            self.assertEqual(trends.chapters, [])
            self.assertEqual(trends.trend_direction, "insufficient_data")
            self.assertEqual(trends.avg_pressure, 0.0)
            self.assertEqual(trends.avg_arc, 0.0)
            self.assertEqual(trends.avg_cinematic, 0.0)

    def test_no_diag_directory(self):
        with TemporaryDirectory() as tmp:
            trends = compute_drama_trends(Path(tmp))
            self.assertEqual(trends.chapters, [])
            self.assertEqual(trends.trend_direction, "insufficient_data")


class TestDramaTrendsComputation(unittest.TestCase):
    def _write_diag(self, diag_dir: Path, chapter_num: int, pressure: int, arc: int, cinematic: int, overall: int, is_mock: bool = False):
        diag_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "chapter_number": chapter_num,
            "pressure_curve_score": pressure,
            "character_arc_score": arc,
            "cinematic_score": cinematic,
            "overall_drama_score": overall,
            "is_mock": is_mock,
            "generated_at": "2026-05-06T12:00:00",
        }
        path = diag_dir / f"第{chapter_num:03d}章_戏剧诊断.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def test_three_chapters_improving(self):
        with TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            diag_dir = project_dir / "04_审核日志"
            self._write_diag(diag_dir, 1, 60, 55, 50, 55)
            self._write_diag(diag_dir, 2, 65, 60, 55, 60)
            self._write_diag(diag_dir, 3, 75, 70, 65, 70)

            trends = compute_drama_trends(project_dir)
            self.assertEqual(len(trends.chapters), 3)
            self.assertEqual(trends.chapters[0].chapter_number, 1)
            self.assertEqual(trends.chapters[2].chapter_number, 3)
            self.assertEqual(len(trends.rolling_avg_overall), 1)  # 3 chapters, window=3 → 1 value
            self.assertAlmostEqual(trends.rolling_avg_overall[0], (55 + 60 + 70) / 3, places=1)
            self.assertEqual(trends.trend_direction, "improving")

    def test_three_chapters_declining(self):
        with TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            diag_dir = project_dir / "04_审核日志"
            self._write_diag(diag_dir, 1, 80, 75, 70, 75)
            self._write_diag(diag_dir, 2, 75, 70, 65, 70)
            self._write_diag(diag_dir, 3, 65, 60, 55, 60)

            trends = compute_drama_trends(project_dir)
            self.assertEqual(trends.trend_direction, "declining")

    def test_three_chapters_stable(self):
        with TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            diag_dir = project_dir / "04_审核日志"
            self._write_diag(diag_dir, 1, 70, 65, 60, 65)
            self._write_diag(diag_dir, 2, 72, 66, 62, 67)
            self._write_diag(diag_dir, 3, 69, 64, 61, 66)

            trends = compute_drama_trends(project_dir)
            self.assertEqual(trends.trend_direction, "stable")

    def test_mock_chapters_excluded_from_rolling_avg(self):
        with TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            diag_dir = project_dir / "04_审核日志"
            self._write_diag(diag_dir, 1, 60, 55, 50, 55, is_mock=True)
            self._write_diag(diag_dir, 2, 70, 65, 60, 65, is_mock=False)
            self._write_diag(diag_dir, 3, 80, 75, 70, 75, is_mock=False)

            trends = compute_drama_trends(project_dir)
            self.assertEqual(len(trends.chapters), 3)
            # rolling avg uses only non-mock scores: [65, 75]
            self.assertEqual(trends.rolling_avg_overall, [70.0])
            # averages exclude mock: (65+75)/2=70
            self.assertAlmostEqual(trends.avg_pressure, (70 + 80) / 2, places=1)
            self.assertAlmostEqual(trends.avg_arc, (65 + 75) / 2, places=1)
            self.assertAlmostEqual(trends.avg_cinematic, (60 + 70) / 2, places=1)

    def test_all_mock_all_excluded(self):
        with TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            diag_dir = project_dir / "04_审核日志"
            self._write_diag(diag_dir, 1, 60, 55, 50, 55, is_mock=True)
            self._write_diag(diag_dir, 2, 65, 60, 55, 60, is_mock=True)

            trends = compute_drama_trends(project_dir)
            self.assertEqual(len(trends.chapters), 2)
            self.assertEqual(trends.rolling_avg_overall, [])
            self.assertEqual(trends.avg_pressure, 0.0)
            self.assertEqual(trends.avg_arc, 0.0)
            self.assertEqual(trends.avg_cinematic, 0.0)
            self.assertEqual(trends.trend_direction, "insufficient_data")

    def test_five_chapters_rolling_window(self):
        with TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            diag_dir = project_dir / "04_审核日志"
            for i, score in enumerate([50, 60, 70, 80, 90], start=1):
                self._write_diag(diag_dir, i, score, score, score, score)

            trends = compute_drama_trends(project_dir)
            # 5 chapters, window=3 → 3 rolling averages
            self.assertEqual(len(trends.rolling_avg_overall), 3)
            self.assertAlmostEqual(trends.rolling_avg_overall[0], (50 + 60 + 70) / 3, places=1)
            self.assertAlmostEqual(trends.rolling_avg_overall[1], (60 + 70 + 80) / 3, places=1)
            self.assertAlmostEqual(trends.rolling_avg_overall[2], (70 + 80 + 90) / 3, places=1)
            self.assertEqual(trends.trend_direction, "improving")

    def test_chapters_sorted_by_number(self):
        with TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            diag_dir = project_dir / "04_审核日志"
            # Write out of order
            self._write_diag(diag_dir, 3, 70, 65, 60, 65)
            self._write_diag(diag_dir, 1, 50, 45, 40, 45)
            self._write_diag(diag_dir, 2, 60, 55, 50, 55)

            trends = compute_drama_trends(project_dir)
            self.assertEqual([c.chapter_number for c in trends.chapters], [1, 2, 3])

    def test_corrupted_json_skipped(self):
        with TemporaryDirectory() as tmp:
            project_dir = Path(tmp)
            diag_dir = project_dir / "04_审核日志"
            self._write_diag(diag_dir, 1, 60, 55, 50, 55)
            diag_dir.mkdir(parents=True, exist_ok=True)
            (diag_dir / "第002章_戏剧诊断.json").write_text("not valid json", encoding="utf-8")
            self._write_diag(diag_dir, 3, 80, 75, 70, 75)

            trends = compute_drama_trends(project_dir)
            self.assertEqual(len(trends.chapters), 2)
            self.assertEqual(trends.chapters[0].chapter_number, 1)
            self.assertEqual(trends.chapters[1].chapter_number, 3)


class TestSchemaValidation(unittest.TestCase):
    def test_chapter_drama_snapshot_defaults(self):
        snap = ChapterDramaSnapshot(chapter_number=1)
        self.assertEqual(snap.chapter_number, 1)
        self.assertEqual(snap.pressure_curve_score, 0)
        self.assertEqual(snap.character_arc_score, 0)
        self.assertEqual(snap.cinematic_score, 0)
        self.assertEqual(snap.overall_drama_score, 0)
        self.assertEqual(snap.is_mock, False)

    def test_drama_trends_defaults(self):
        trends = DramaTrends()
        self.assertEqual(trends.chapters, [])
        self.assertEqual(trends.trend_direction, "insufficient_data")
        self.assertEqual(trends.avg_pressure, 0.0)

    def test_drama_trends_invalid_direction_rejected(self):
        from pydantic import ValidationError
        with self.assertRaises(ValidationError):
            DramaTrends(trend_direction="upward")  # type: ignore[arg-type]


class TestWithRealProjectData(unittest.TestCase):
    """使用项目真实诊断 JSON 文件进行集成测试。"""
    PROJECT_DIR = Path(__file__).parent.parent.resolve()

    def test_trends_from_project_data(self):
        trends = compute_drama_trends(self.PROJECT_DIR)
        self.assertIsNotNone(trends)
        # 只要不抛异常就算通过；如果有数据则验证结构
        if trends.chapters:
            for snap in trends.chapters:
                self.assertGreaterEqual(snap.chapter_number, 1)
                self.assertGreaterEqual(snap.overall_drama_score, 0)
                self.assertLessEqual(snap.overall_drama_score, 100)
            self.assertIn(trends.trend_direction, {"improving", "declining", "stable", "insufficient_data"})


if __name__ == "__main__":
    unittest.main()
