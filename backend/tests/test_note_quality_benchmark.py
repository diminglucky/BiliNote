import json
import pathlib
import tempfile
import unittest

from PIL import Image, ImageDraw, ImageFilter

from app.benchmark.note_quality import load_task_report
from app.enmus.task_status_enums import TaskStatus
from app.utils.task_status_writer import write_status_record


class TestNoteQualityBenchmark(unittest.TestCase):
    def _write_task_payload(self, note_dir: pathlib.Path, task_id: str, markdown: str) -> None:
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
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def test_report_detects_duplicate_low_quality_and_unresolved_markers(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
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
        with tempfile.TemporaryDirectory() as tmp_dir:
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


if __name__ == "__main__":
    unittest.main()
