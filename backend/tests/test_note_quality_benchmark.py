import json
import pathlib
import shutil
import sys
import unittest
import uuid

from PIL import Image, ImageDraw, ImageFilter

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.benchmark.note_quality import load_task_report
from app.enmus.task_status_enums import TaskStatus
from app.utils.task_status_writer import write_status_record

TEST_TMP_ROOT = ROOT / ".test_tmp"


class ProjectTempDir:
    def __init__(self, prefix="quality_benchmark_"):
        self.prefix = prefix
        self.path: pathlib.Path | None = None

    def __enter__(self):
        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.path = TEST_TMP_ROOT / f"{self.prefix}{uuid.uuid4().hex}"
        self.path.mkdir()
        return str(self.path)

    def __exit__(self, _exc_type, _exc, _tb):
        if self.path is not None:
            shutil.rmtree(self.path, ignore_errors=True)


class TestNoteQualityBenchmark(unittest.TestCase):
    def _write_task_payload(
        self,
        note_dir: pathlib.Path,
        task_id: str,
        markdown: str,
        visual_report: dict | None = None,
    ) -> None:
        (note_dir / f"{task_id}.json").write_text(
            json.dumps(
                {
                    "markdown": markdown,
                    "transcript": {
                        "language": "zh",
                        "full_text": "demo transcript",
                        "segments": [{"start": 0, "end": 10, "text": "demo transcript"}],
                    },
                    "audio_meta": {
                        "file_path": "audio.mp3",
                        "title": "demo",
                        "duration": 120,
                        "cover_url": None,
                        "platform": "bilibili",
                        "video_id": "BV1",
                        "raw_info": {},
                        "video_path": "video.mp4",
                    },
                    "generation_token": "generation-1",
                    "enhance_token": "enhance-1",
                    "visual_report": visual_report or {},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def test_report_detects_duplicate_low_quality_and_unresolved_markers(self):
        with ProjectTempDir() as tmp_dir:
            root = pathlib.Path(tmp_dir)
            note_dir = root / "note_results"
            static_dir = root / "static"
            screenshot_dir = static_dir / "screenshots"
            note_dir.mkdir()
            screenshot_dir.mkdir(parents=True)

            clear_path = screenshot_dir / "clear.jpg"
            blank_path = screenshot_dir / "blank.jpg"
            duplicate_path = screenshot_dir / "duplicate.jpg"

            img = Image.new("RGB", (1280, 720), "white")
            draw = ImageDraw.Draw(img)
            for row in range(10):
                draw.text((90, 70 + row * 60), f"Important final result line {row}", fill="black")
            img.save(clear_path, quality=95)
            img.save(duplicate_path, quality=95)
            img.filter(ImageFilter.GaussianBlur(radius=6)).save(blank_path, quality=95)

            markdown = (
                "## Demo Section *Content-[00:00]*\n\n"
                "This section has enough context before the image so placement can be audited.\n\n"
                "![](/static/screenshots/clear.jpg)\n\n"
                "More explanation after the first useful image.\n\n"
                "![](/static/screenshots/duplicate.jpg)\n\n"
                "## Weak Section *Content-[01:00]*\n\n"
                "The next image is intentionally weak for quality checks.\n\n"
                "![](/static/screenshots/blank.jpg)\n\n"
                "*Screenshot-[01:10]*\n\n"
                "## AI Summary\n\n"
                "Summary text.\n"
            )
            self._write_task_payload(note_dir, "task-1", markdown)
            write_status_record(
                "task-1",
                TaskStatus.PENDING,
                generation_token="generation-1",
                output_dir=note_dir,
            )
            write_status_record(
                "task-1",
                TaskStatus.ENHANCING,
                message="enhancing screenshots",
                generation_token="generation-1",
                output_dir=note_dir,
            )
            write_status_record(
                "task-1",
                TaskStatus.SUCCESS,
                generation_token="generation-1",
                output_dir=note_dir,
            )

            report = load_task_report("task-1", note_dir, static_dir)

        self.assertEqual(report.image_count, 3)
        self.assertEqual(report.unresolved_marker_count, 1)
        self.assertGreaterEqual(report.duplicate_image_pairs, 1)
        self.assertGreaterEqual(report.low_quality_image_count, 1)
        self.assertTrue(any(item.status == TaskStatus.ENHANCING.value for item in report.stage_timings))
        self.assertFalse(report.pass_quality_gate)

    def test_status_writer_preserves_history_for_stage_timing(self):
        with ProjectTempDir() as tmp_dir:
            note_dir = pathlib.Path(tmp_dir)
            write_status_record(
                "task-1",
                TaskStatus.PENDING,
                generation_token="generation-1",
                output_dir=note_dir,
            )
            write_status_record(
                "task-1",
                TaskStatus.DOWNLOADING,
                message="download started",
                generation_token="generation-1",
                output_dir=note_dir,
            )
            payload = json.loads((note_dir / "task-1.status.json").read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], TaskStatus.DOWNLOADING.value)
        self.assertEqual(payload["generation_token"], "generation-1")
        self.assertEqual([item["status"] for item in payload["history"]], ["PENDING", "DOWNLOADING"])
        self.assertEqual(payload["history"][-1]["message"], "download started")

    def test_partial_success_is_not_quality_gate_pass(self):
        with ProjectTempDir() as tmp_dir:
            root = pathlib.Path(tmp_dir)
            note_dir = root / "note_results"
            static_dir = root / "static"
            note_dir.mkdir()
            static_dir.mkdir()
            markdown = (
                "## Demo Section *Content-[00:00]*\n\n"
                "This is a complete enough note body with summary signal and enough context "
                "to isolate partial success as the only issue.\n\n"
                "## AI Summary\n\n"
                "Summary text.\n"
            )
            self._write_task_payload(note_dir, "task-1", markdown)
            write_status_record(
                "task-1",
                TaskStatus.PARTIAL_SUCCESS,
                message="笔记已完成，部分截图未插入",
                generation_token="generation-1",
                output_dir=note_dir,
            )

            report = load_task_report("task-1", note_dir, static_dir)

        self.assertEqual(report.status, TaskStatus.PARTIAL_SUCCESS.value)
        self.assertTrue(any(issue.startswith("partial-success") for issue in report.issues))
        self.assertFalse(report.pass_quality_gate)

    def test_report_detects_clustered_images_without_markdown_context(self):
        with ProjectTempDir() as tmp_dir:
            root = pathlib.Path(tmp_dir)
            note_dir = root / "note_results"
            static_dir = root / "static"
            screenshot_dir = static_dir / "screenshots"
            note_dir.mkdir()
            screenshot_dir.mkdir(parents=True)

            for filename, color in [
                ("first.jpg", "white"),
                ("second.jpg", "lightgray"),
                ("third.jpg", "white"),
                ("fourth.jpg", "lightgray"),
            ]:
                img = Image.new("RGB", (1280, 720), color)
                draw = ImageDraw.Draw(img)
                for row in range(10):
                    draw.text((90, 70 + row * 60), f"Useful screen detail {row}", fill="black")
                img.save(screenshot_dir / filename, quality=95)

            markdown = (
                "## Demo Section *Content-[00:00]*\n\n"
                "This section has enough explanation before images, but the following two "
                "screenshots are stacked without separate prose, which makes the note hard "
                "to read and should be caught by the quality benchmark.\n\n"
                "![](/static/screenshots/first.jpg)\n\n"
                "![](/static/screenshots/second.jpg)\n\n"
                "![](/static/screenshots/third.jpg)\n\n"
                "### Separate result screen\n\n"
                "![](/static/screenshots/fourth.jpg)\n\n"
                "## AI Summary\n\n"
                "Summary text with enough words to avoid unrelated markdown length failures.\n"
            )
            self._write_task_payload(note_dir, "task-1", markdown)
            write_status_record(
                "task-1",
                TaskStatus.SUCCESS,
                generation_token="generation-1",
                output_dir=note_dir,
            )

            report = load_task_report("task-1", note_dir, static_dir)

        cluster_issues = [
            issue for issue in report.issues
            if issue.endswith(":image-cluster")
        ]
        self.assertGreaterEqual(len(cluster_issues), 2)
        by_name = {pathlib.Path(item.path or item.url).name: item for item in report.images}
        self.assertNotIn("image-cluster", by_name["fourth.jpg"].issues)
        self.assertFalse(report.pass_quality_gate)

    def test_source_limited_video_does_not_fail_only_for_low_resolution_images(self):
        with ProjectTempDir() as tmp_dir:
            root = pathlib.Path(tmp_dir)
            note_dir = root / "note_results"
            static_dir = root / "static"
            screenshot_dir = static_dir / "screenshots"
            note_dir.mkdir()
            screenshot_dir.mkdir(parents=True)

            image_path = screenshot_dir / "source_480p.jpg"
            img = Image.new("RGB", (852, 480), (248, 250, 252))
            draw = ImageDraw.Draw(img)
            draw.rectangle((0, 0, 852, 48), fill=(20, 30, 45))
            draw.rectangle((28, 76, 380, 430), outline=(37, 99, 235), width=3)
            draw.rectangle((410, 76, 824, 430), outline=(22, 163, 74), width=3)
            for row in range(9):
                y = 96 + row * 34
                draw.rectangle((48, y, 350, y + 14), fill=(30 + row * 12, 90, 180))
                draw.line((430, y + 8, 790, y + 8), fill=(15, 23, 42), width=2)
                draw.text((436, y + 14), f"Result row {row}", fill=(15, 23, 42))
            for col in range(5):
                x = 60 + col * 62
                draw.ellipse((x, 380, x + 26, 406), fill=(234, 88, 12))
            img.save(image_path, quality=95)

            markdown = (
                "## Demo Section *Content-[00:00]*\n\n"
                "This section has enough useful explanation before the image so the placement "
                "is not considered thin by the quality benchmark. It describes the visible "
                "interface, the final output area, the comparison table, and why the screenshot "
                "should still be accepted when the original video source is only 480p. The note "
                "body intentionally contains enough prose to pass the normal markdown length "
                "gate, because this test isolates source-limited screenshot resolution instead "
                "of relaxing the rest of the quality benchmark.\n\n"
                "![](/static/screenshots/source_480p.jpg)\n\n"
                "## AI Summary\n\n"
                "Summary text. This generated note remains useful because the source-limited "
                "image is clear enough for the original video quality, and no screenshot slot "
                "was missing, duplicated, or placed without surrounding context.\n"
            )
            self._write_task_payload(note_dir, "task-1", markdown)
            payload_path = note_dir / "task-1.json"
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
            payload["audio_meta"]["raw_info"] = {
                "video_quality": {
                    "resolution": "852x480",
                    "width": 852,
                    "height": 480,
                    "screenshot_ready": False,
                    "degraded": True,
                }
            }
            payload_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            write_status_record(
                "task-1",
                TaskStatus.SUCCESS,
                generation_token="generation-1",
                output_dir=note_dir,
            )

            report = load_task_report("task-1", note_dir, static_dir)

        self.assertTrue(report.source_limited_screenshots)
        self.assertEqual(report.low_quality_image_count, 0)
        self.assertFalse(any("low-resolution" in issue for issue in report.issues))
        self.assertTrue(report.pass_quality_gate)

    def test_report_includes_visual_report_and_flags_empty_success(self):
        with ProjectTempDir() as tmp_dir:
            root = pathlib.Path(tmp_dir)
            note_dir = root / "note_results"
            static_dir = root / "static"
            note_dir.mkdir()
            static_dir.mkdir()
            markdown = (
                "## Demo Section *Content-[00:00]*\n\n"
                "This section explains a UI operation that should have produced a screenshot, "
                "but every planned visual slot failed.\n\n"
                "## AI Summary\n\n"
                "Summary text.\n"
            )
            visual_report = {
                "planned_slots": 2,
                "successful_slots": 0,
                "failed_slots": 2,
                "duplicate_slots": 0,
                "slots": [
                    {"slot_id": 0, "status": "failed", "reason": "blank frame"},
                    {"slot_id": 1, "status": "failed", "reason": "duplicate frame"},
                ],
            }
            self._write_task_payload(note_dir, "task-1", markdown, visual_report=visual_report)
            write_status_record(
                "task-1",
                TaskStatus.SUCCESS,
                generation_token="generation-1",
                output_dir=note_dir,
            )

            report = load_task_report("task-1", note_dir, static_dir)

        self.assertEqual(report.visual_report["planned_slots"], 2)
        self.assertTrue(any(issue == "visual-report-no-successful-screenshots" for issue in report.issues))
        self.assertFalse(report.pass_quality_gate)

    def test_report_flags_risky_visual_selection_diagnostics(self):
        with ProjectTempDir() as tmp_dir:
            root = pathlib.Path(tmp_dir)
            note_dir = root / "note_results"
            static_dir = root / "static"
            note_dir.mkdir()
            static_dir.mkdir()
            markdown = (
                "## Demo Section *Content-[00:00]*\n\n"
                "This section has enough content and a generated screenshot.\n"
                "![](/static/screenshots/one.jpg)\n\n"
                "## AI Summary\n\n"
                "Summary text.\n"
            )
            screenshots_dir = static_dir / "screenshots"
            screenshots_dir.mkdir()
            img = Image.new("RGB", (1280, 720), (120, 140, 160))
            draw = ImageDraw.Draw(img)
            for row in range(8):
                draw.text((80, 80 + row * 58), f"Result line {row}", fill="white")
            img.save(screenshots_dir / "one.jpg", quality=95)
            visual_report = {
                "planned_slots": 1,
                "successful_slots": 1,
                "failed_slots": 0,
                "duplicate_slots": 0,
                "slots": [
                    {
                        "slot_id": 0,
                        "status": "inserted",
                        "selection": {
                            "candidate_count": 1,
                            "selected_score": 0.39,
                            "review_mode": "strict",
                            "review_used": False,
                        },
                    },
                ],
            }
            self._write_task_payload(note_dir, "task-1", markdown, visual_report=visual_report)
            write_status_record(
                "task-1",
                TaskStatus.SUCCESS,
                generation_token="generation-1",
                output_dir=note_dir,
            )

            report = load_task_report("task-1", note_dir, static_dir)

        self.assertIn("visual-slot:0:single-candidate-selection", report.issues)
        self.assertIn("visual-slot:0:low-selected-score:0.390", report.issues)
        self.assertIn("visual-slot:0:strict-review-not-used", report.issues)

    def test_report_ignores_low_score_for_skipped_optional_visual_slots(self):
        with ProjectTempDir() as tmp_dir:
            root = pathlib.Path(tmp_dir)
            note_dir = root / "note_results"
            static_dir = root / "static"
            note_dir.mkdir()
            static_dir.mkdir()
            markdown = (
                "## Demo Section *Content-[00:00]*\n\n"
                "This section has enough generated note content and one useful screenshot.\n"
                "The optional skipped slot should not affect the visible note quality.\n"
                "## AI Summary\n\n"
                "Summary text.\n"
            )
            visual_report = {
                "planned_slots": 2,
                "successful_slots": 1,
                "failed_slots": 0,
                "skipped_slots": 1,
                "duplicate_slots": 0,
                "slots": [
                    {
                        "slot_id": 0,
                        "status": "inserted",
                        "selection": {"candidate_count": 2, "selected_score": 0.72},
                    },
                    {
                        "slot_id": 1,
                        "status": "skipped",
                        "selection": {"candidate_count": 1, "selected_score": 0.05},
                    },
                ],
            }
            self._write_task_payload(note_dir, "task-1", markdown, visual_report=visual_report)
            write_status_record(
                "task-1",
                TaskStatus.SUCCESS,
                generation_token="generation-1",
                output_dir=note_dir,
            )

            report = load_task_report("task-1", note_dir, static_dir)

        self.assertNotIn("visual-slot:1:single-candidate-selection", report.issues)
        self.assertNotIn("visual-slot:1:low-selected-score:0.050", report.issues)


if __name__ == "__main__":
    unittest.main()
