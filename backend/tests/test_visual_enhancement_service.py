import importlib.util
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class TestVisualEnhancementService(unittest.TestCase):
    def _load_service(self):
        sys.modules.pop("app.services.visual_enhancement_service", None)

        module_path = ROOT / "app" / "services" / "visual_enhancement_service.py"
        spec = importlib.util.spec_from_file_location(
            "app.services.visual_enhancement_service",
            module_path,
        )
        if spec is None or spec.loader is None:
            raise ImportError("visual_enhancement_service module spec not found")
        module = importlib.util.module_from_spec(spec)
        sys.modules["app.services.visual_enhancement_service"] = module
        spec.loader.exec_module(module)
        return module.VisualEnhancementService

    def _write_result(
        self,
        output_dir,
        token="token-1",
        generation_token="generation-1",
        markdown="## Demo\n",
    ):
        result_path = pathlib.Path(output_dir) / "task-1.json"
        result_path.write_text(
            json.dumps(
                {
                    "markdown": markdown,
                    "transcript": {"language": "zh", "full_text": "demo", "segments": []},
                    "audio_meta": {
                        "file_path": "audio.mp3",
                        "title": "demo",
                        "duration": 60,
                        "cover_url": None,
                        "platform": "bilibili",
                        "video_id": "BV1",
                        "raw_info": {},
                        "video_path": "video.mp4",
                    },
                    "enhance_token": token,
                    "generation_token": generation_token,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        return result_path

    def test_enhance_saved_note_updates_result_markdown_and_reindexes(self):
        VisualEnhancementService = self._load_service()
        status_updates = []

        class _StatusWriter:
            def _update_status(self, task_id, status, message=None):
                status_updates.append((task_id, getattr(status, "value", status), message))

        class _ScreenshotAgent:
            def insert_screenshots(self, markdown, video_path, duration, gpt, on_markdown_update=None):
                return markdown + "\n![](/static/screenshots/key.jpg)\n"

        with tempfile.TemporaryDirectory() as tmp_dir:
            result_path = self._write_result(tmp_dir)

            with patch.object(VisualEnhancementService, "_reindex_task") as reindex:
                changed = VisualEnhancementService(
                    tmp_dir,
                    screenshot_agent_factory=_ScreenshotAgent,
                    status_writer=_StatusWriter(),
                ).enhance_saved_note(
                    "task-1",
                    "video.mp4",
                    60,
                    "bilibili",
                    enhance_token="token-1",
                    generation_token="generation-1",
                )

            payload = json.loads(result_path.read_text(encoding="utf-8"))

        self.assertTrue(changed)
        self.assertIn("key.jpg", payload["markdown"])
        self.assertEqual(status_updates[-1][1], "SUCCESS")
        reindex.assert_called_once_with("task-1")

    def test_default_enhancement_path_uses_screenshot_agent_without_note_generator(self):
        VisualEnhancementService = self._load_service()
        calls = []

        class _ScreenshotAgent:
            def insert_screenshots(self, markdown, video_path, duration, gpt, on_markdown_update=None):
                calls.append((markdown, str(video_path), duration, gpt, on_markdown_update))
                return markdown + "\n![](/static/screenshots/key.jpg)\n"

        with tempfile.TemporaryDirectory() as tmp_dir:
            result_path = self._write_result(tmp_dir)

            with patch.object(VisualEnhancementService, "_reindex_task"):
                changed = VisualEnhancementService(
                    tmp_dir,
                    screenshot_agent_factory=_ScreenshotAgent,
                ).enhance_saved_note(
                    "task-1",
                    "video.mp4",
                    60,
                    "bilibili",
                    enhance_token="token-1",
                    generation_token="generation-1",
                )

            payload = json.loads(result_path.read_text(encoding="utf-8"))

        self.assertTrue(changed)
        self.assertIn("key.jpg", payload["markdown"])
        self.assertEqual(len(calls), 1)

    def test_enhance_saved_note_publishes_incremental_markdown_updates(self):
        VisualEnhancementService = self._load_service()
        snapshots = []

        class _StatusWriter:
            def _update_status(self, task_id, status, message=None):
                snapshots.append((getattr(status, "value", status), message))

        class _ScreenshotAgent:
            def insert_screenshots(self, markdown, video_path, duration, gpt, on_markdown_update=None):
                on_update = on_markdown_update
                first = markdown + "\n![](/static/screenshots/one.jpg)\n"
                on_update(first, 10, "![](/static/screenshots/one.jpg)")
                second = first + "\n![](/static/screenshots/two.jpg)\n"
                on_update(second, 20, "![](/static/screenshots/two.jpg)")
                return second

        with tempfile.TemporaryDirectory() as tmp_dir:
            result_path = self._write_result(tmp_dir)

            with patch.object(VisualEnhancementService, "_reindex_task"):
                changed = VisualEnhancementService(
                    tmp_dir,
                    screenshot_agent_factory=_ScreenshotAgent,
                    status_writer=_StatusWriter(),
                ).enhance_saved_note(
                    "task-1",
                    "video.mp4",
                    60,
                    "bilibili",
                    enhance_token="token-1",
                    generation_token="generation-1",
                )

            payload = json.loads(result_path.read_text(encoding="utf-8"))

        self.assertTrue(changed)
        self.assertIn("one.jpg", payload["markdown"])
        self.assertIn("two.jpg", payload["markdown"])
        self.assertTrue(any("已插入 1 张" in (message or "") for _status, message in snapshots))
        self.assertTrue(any("已插入 2 张" in (message or "") for _status, message in snapshots))

    def test_enhance_saved_note_failure_keeps_base_note_successful(self):
        VisualEnhancementService = self._load_service()
        status_updates = []

        class _StatusWriter:
            def _update_status(self, task_id, status, message=None):
                status_updates.append((task_id, getattr(status, "value", status), message))

        class _ScreenshotAgent:
            def insert_screenshots(self, *_args, **_kwargs):
                raise RuntimeError("bad screenshot")

        with tempfile.TemporaryDirectory() as tmp_dir:
            result_path = self._write_result(tmp_dir)

            changed = VisualEnhancementService(
                tmp_dir,
                screenshot_agent_factory=_ScreenshotAgent,
                status_writer=_StatusWriter(),
            ).enhance_saved_note(
                "task-1",
                "video.mp4",
                60,
                "bilibili",
                enhance_token="token-1",
                generation_token="generation-1",
            )

            payload = json.loads(result_path.read_text(encoding="utf-8"))

        self.assertFalse(changed)
        self.assertEqual(payload["markdown"], "## Demo\n")
        self.assertEqual(status_updates[-1][1], "SUCCESS")
        self.assertIn("bad screenshot", status_updates[-1][2])

    def test_enhance_saved_note_reindexes_partial_increment_after_later_failure(self):
        VisualEnhancementService = self._load_service()

        class _ScreenshotAgent:
            def _update_status(self, _task_id, _status, message=None):
                pass

            def insert_screenshots(self, markdown, video_path, duration, gpt, on_markdown_update=None):
                on_markdown_update(
                    markdown + "\n![](/static/screenshots/one.jpg)\n",
                    10,
                    "![](/static/screenshots/one.jpg)",
                )
                raise RuntimeError("later screenshot failed")

        with tempfile.TemporaryDirectory() as tmp_dir:
            result_path = self._write_result(tmp_dir)

            with patch.object(VisualEnhancementService, "_reindex_task") as reindex:
                changed = VisualEnhancementService(
                    tmp_dir,
                    screenshot_agent_factory=_ScreenshotAgent,
                ).enhance_saved_note(
                    "task-1",
                    "video.mp4",
                    60,
                    "bilibili",
                    enhance_token="token-1",
                    generation_token="generation-1",
                )

            payload = json.loads(result_path.read_text(encoding="utf-8"))

        self.assertFalse(changed)
        self.assertIn("one.jpg", payload["markdown"])
        reindex.assert_called_once_with("task-1")

    def test_stale_token_does_not_update_status_or_markdown(self):
        VisualEnhancementService = self._load_service()
        status_updates = []
        post_process_calls = []

        class _StatusWriter:
            def _update_status(self, task_id, status, message=None):
                status_updates.append((task_id, getattr(status, "value", status), message))

        class _ScreenshotAgent:
            def insert_screenshots(self, markdown, video_path, duration, gpt, on_markdown_update=None):
                post_process_calls.append(markdown)
                return markdown + "\nstale\n"

        with tempfile.TemporaryDirectory() as tmp_dir:
            result_path = self._write_result(tmp_dir, token="new-token")

            changed = VisualEnhancementService(
                tmp_dir,
                screenshot_agent_factory=_ScreenshotAgent,
                status_writer=_StatusWriter(),
            ).enhance_saved_note(
                "task-1",
                "video.mp4",
                60,
                "bilibili",
                enhance_token="old-token",
                generation_token="generation-1",
            )

            payload = json.loads(result_path.read_text(encoding="utf-8"))

        self.assertFalse(changed)
        self.assertEqual(payload["markdown"], "## Demo\n")
        self.assertEqual(status_updates, [])
        self.assertEqual(post_process_calls, [])

    def test_stale_token_after_processing_does_not_overwrite_new_result(self):
        VisualEnhancementService = self._load_service()
        status_updates = []
        output_dir_holder = {}

        class _StatusWriter:
            def _update_status(self, task_id, status, message=None):
                status_updates.append((task_id, getattr(status, "value", status), message))

        class _ScreenshotAgent:
            def insert_screenshots(self, markdown, video_path, duration, gpt, on_markdown_update=None):
                result_path = pathlib.Path(output_dir_holder["dir"]) / "task-1.json"
                current = json.loads(result_path.read_text(encoding="utf-8"))
                current["markdown"] = "## Fresh retry\n"
                current["enhance_token"] = "new-token"
                result_path.write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8")
                return markdown + "\nold screenshot\n"

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir_holder["dir"] = tmp_dir
            result_path = self._write_result(tmp_dir, token="old-token")

            changed = VisualEnhancementService(
                tmp_dir,
                screenshot_agent_factory=_ScreenshotAgent,
                status_writer=_StatusWriter(),
            ).enhance_saved_note(
                "task-1",
                "video.mp4",
                60,
                "bilibili",
                enhance_token="old-token",
                generation_token="generation-1",
            )

            payload = json.loads(result_path.read_text(encoding="utf-8"))

        self.assertFalse(changed)
        self.assertEqual(payload["markdown"], "## Fresh retry\n")
        self.assertEqual(payload["enhance_token"], "new-token")
        self.assertNotEqual(status_updates[-1][1], "SUCCESS")

    def test_stale_generation_token_does_not_update_status_even_if_enhance_token_matches(self):
        VisualEnhancementService = self._load_service()
        status_updates = []

        class _StatusWriter:
            def _update_status(self, task_id, status, message=None):
                status_updates.append((task_id, getattr(status, "value", status), message))

        class _ScreenshotAgent:
            def insert_screenshots(self, markdown, video_path, duration, gpt, on_markdown_update=None):
                return markdown + "\nold screenshot\n"

        with tempfile.TemporaryDirectory() as tmp_dir:
            result_path = self._write_result(
                tmp_dir,
                token="same-enhance-token",
                generation_token="new-generation",
            )

            changed = VisualEnhancementService(
                tmp_dir,
                screenshot_agent_factory=_ScreenshotAgent,
                status_writer=_StatusWriter(),
            ).enhance_saved_note(
                "task-1",
                "video.mp4",
                60,
                "bilibili",
                enhance_token="same-enhance-token",
                generation_token="old-generation",
            )

            payload = json.loads(result_path.read_text(encoding="utf-8"))

        self.assertFalse(changed)
        self.assertEqual(payload["markdown"], "## Demo\n")
        self.assertEqual(status_updates, [])


if __name__ == "__main__":
    unittest.main()
