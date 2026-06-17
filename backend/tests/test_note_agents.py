import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from app.agents.note_agents import (
    ChatIndexRequest,
    ChatRagAgent,
    DownloadAgent,
    DownloadRequest,
    MarkdownComposerAgent,
    MarkdownComposeRequest,
    NoteWriterAgent,
    NoteWriteRequest,
    TranscriptAgent,
    TranscriptRequest,
    VisualEnhancementAgent,
    VisualEnhancementRequest,
)
from app.agents.base import AgentExecutionContext, StepExecutionMode
from app.agents.planner import build_note_execution_plan
from app.enmus.task_status_enums import TaskStatus
from app.services.note import NoteGenerator
from app.models.transcriber_model import TranscriptResult, TranscriptSegment
from app.models.audio_model import AudioDownloadResult


class TestNoteAgents(unittest.TestCase):
    def test_write_status_does_not_initialize_generator(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            NoteGenerator.write_status(
                "task-1",
                TaskStatus.PENDING,
                generation_token="generation-1",
                output_dir=pathlib.Path(tmp_dir),
            )

            status_path = pathlib.Path(tmp_dir) / "task-1.status.json"
            payload = json.loads(status_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], TaskStatus.PENDING.value)
        self.assertEqual(payload["generation_token"], "generation-1")

    def test_download_agent_forwards_to_generator_download_media(self):
        calls = []
        expected_audio = object()
        downloader = object()

        class _Generator:
            def _download_media(self, **kwargs):
                calls.append(kwargs)
                return expected_audio

        with tempfile.TemporaryDirectory() as tmp_dir:
            request = DownloadRequest(
                video_url="https://example.com/video",
                platform="bilibili",
                quality="medium",
                audio_cache_file=pathlib.Path(tmp_dir) / "task_audio.json",
                downloader=downloader,
                screenshot=True,
                video_understanding=True,
                video_interval=5,
                grid_size=[2, 2],
                skip_download=False,
            )

            result = DownloadAgent(_Generator()).run(request)

        self.assertIs(result, expected_audio)
        self.assertIs(calls[0]["downloader"], downloader)
        self.assertEqual(calls[0]["status_phase"], TaskStatus.DOWNLOADING)
        self.assertTrue(calls[0]["screenshot"])
        self.assertTrue(calls[0]["video_understanding"])

    def test_download_agent_full_download_decision(self):
        self.assertFalse(
            DownloadAgent.needs_full_download(
                has_transcript=True,
                wants_screenshot=False,
                video_understanding=False,
            )
        )
        self.assertTrue(
            DownloadAgent.needs_full_download(
                has_transcript=False,
                wants_screenshot=False,
                video_understanding=False,
            )
        )
        self.assertTrue(
            DownloadAgent.needs_full_download(
                has_transcript=True,
                wants_screenshot=True,
                video_understanding=False,
            )
        )

    def test_transcript_agent_loads_cache_before_platform_subtitles(self):
        class _Downloader:
            def download_subtitles(self, _url):
                raise AssertionError("platform subtitles should not be called")

        with tempfile.TemporaryDirectory() as tmp_dir:
            cache_path = pathlib.Path(tmp_dir) / "task_transcript.json"
            cache_path.write_text(
                json.dumps(
                    {
                        "language": "zh",
                        "full_text": "cached transcript",
                        "segments": [{"start": 0, "end": 2, "text": "cached transcript"}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            transcript = TranscriptAgent(object()).load_cached_or_platform_subtitles(
                "https://example.com/video",
                _Downloader(),
                cache_path,
            )

        self.assertIsNotNone(transcript)
        self.assertEqual(transcript.full_text, "cached transcript")
        self.assertEqual(len(transcript.segments), 1)

    def test_transcript_agent_writes_platform_subtitles_to_cache(self):
        source = TranscriptResult(
            language="zh",
            full_text="platform transcript",
            segments=[TranscriptSegment(start=1, end=3, text="platform transcript")],
        )

        class _Downloader:
            def download_subtitles(self, _url):
                return source

        with tempfile.TemporaryDirectory() as tmp_dir:
            cache_path = pathlib.Path(tmp_dir) / "task_transcript.json"
            transcript = TranscriptAgent(object()).load_cached_or_platform_subtitles(
                "https://example.com/video",
                _Downloader(),
                cache_path,
            )
            cached = json.loads(cache_path.read_text(encoding="utf-8"))

        self.assertIs(transcript, source)
        self.assertEqual(cached["full_text"], "platform transcript")
        self.assertEqual(cached["segments"][0]["start"], 1)

    def test_transcript_agent_forwards_fallback_transcription(self):
        calls = []
        expected = object()
        downloader = object()

        class _Generator:
            def _transcribe_audio(self, **kwargs):
                calls.append(kwargs)
                return expected

        with tempfile.TemporaryDirectory() as tmp_dir:
            result = TranscriptAgent(_Generator()).run(
                TranscriptRequest(
                    video_url="https://example.com/video",
                    audio_file="audio.mp3",
                    transcript_cache_file=pathlib.Path(tmp_dir) / "task_transcript.json",
                    downloader=downloader,
                    task_id="task-1",
                )
            )

        self.assertIs(result, expected)
        self.assertEqual(calls[0]["status_phase"], TaskStatus.TRANSCRIBING)
        self.assertEqual(calls[0]["audio_file"], "audio.mp3")

    def test_transcript_agent_resolve_uses_fallback_when_subtitles_missing(self):
        calls = []
        fallback = object()

        class _Downloader:
            def download_subtitles(self, _url):
                return None

        class _Generator:
            def _transcribe_audio(self, **kwargs):
                calls.append(kwargs)
                return fallback

        with tempfile.TemporaryDirectory() as tmp_dir:
            result = TranscriptAgent(_Generator()).resolve(
                TranscriptRequest(
                    video_url="https://example.com/video",
                    audio_file="audio.mp3",
                    transcript_cache_file=pathlib.Path(tmp_dir) / "task_transcript.json",
                    downloader=_Downloader(),
                    task_id="task-1",
                )
            )

        self.assertIs(result, fallback)
        self.assertEqual(calls[0]["audio_file"], "audio.mp3")

    def test_note_writer_agent_forwards_to_generator_summarize_text(self):
        calls = []

        class _Generator:
            def _summarize_text(self, **kwargs):
                calls.append(kwargs)
                return "## Note\n"

        request = NoteWriteRequest(
            audio_meta=object(),
            transcript=object(),
            gpt=object(),
            markdown_cache_file=pathlib.Path("task_markdown.md"),
            link=True,
            screenshot=True,
            formats=["link", "screenshot"],
            style="detailed",
            extras="extra",
            video_img_urls=["image.jpg"],
        )

        result = NoteWriterAgent(_Generator()).run(request)

        self.assertEqual(result, "## Note\n")
        self.assertTrue(calls[0]["link"])
        self.assertTrue(calls[0]["screenshot"])
        self.assertEqual(calls[0]["formats"], ["link", "screenshot"])
        self.assertEqual(calls[0]["video_img_urls"], ["image.jpg"])

    def test_markdown_composer_agent_forwards_to_generator_post_process(self):
        calls = []

        class _Generator:
            def _post_process_markdown(self, **kwargs):
                calls.append(kwargs)
                return kwargs["markdown"] + "\nprocessed"

        request = MarkdownComposeRequest(
            markdown="## Note",
            video_path=pathlib.Path("video.mp4"),
            formats=["screenshot"],
            audio_meta=object(),
            platform="bilibili",
            gpt=object(),
            transcript_segments=[{"start": 1, "end": 2, "text": "demo"}],
        )

        result = MarkdownComposerAgent(_Generator()).run(request)

        self.assertEqual(result, "## Note\nprocessed")
        self.assertEqual(calls[0]["formats"], ["screenshot"])
        self.assertEqual(calls[0]["platform"], "bilibili")
        self.assertEqual(calls[0]["transcript_segments"][0]["text"], "demo")

    def test_chat_rag_agent_indexes_task(self):
        indexed = []

        class _VectorStore:
            def index_task(self, task_id):
                indexed.append(task_id)

        result = ChatRagAgent(vector_store_factory=_VectorStore).run(
            ChatIndexRequest(task_id="task-1")
        )

        self.assertTrue(result)
        self.assertEqual(indexed, ["task-1"])

    def test_visual_enhancement_agent_reports_missing_video_path(self):
        updates = []
        note = type("_Note", (), {"audio_meta": type("_Meta", (), {"video_path": None})()})()

        agent = VisualEnhancementAgent(
            executor=object(),
            status_updater=lambda *args: updates.append(args),
        )

        result = agent.submit(
            VisualEnhancementRequest(
                task_id="task-1",
                note=note,
                platform="bilibili",
                enhance_token="enhance-1",
                generation_token="generation-1",
            )
        )

        self.assertIsNone(result)
        self.assertEqual(updates[0][0], "task-1")
        self.assertEqual(updates[0][3], TaskStatus.SUCCESS)

    def test_visual_enhancement_agent_submits_existing_video(self):
        submitted = []
        updates = []

        class _Future:
            def add_done_callback(self, callback):
                self.callback = callback

        future = _Future()

        class _Executor:
            def submit(self, fn, *args):
                submitted.append((fn, args))
                return future

        class _Service:
            def enhance_saved_note(self, *_args):
                return True

        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = pathlib.Path(tmp_dir) / "video.mp4"
            video_path.write_bytes(b"video")
            note = type(
                "_Note",
                (),
                {"audio_meta": type("_Meta", (), {"video_path": str(video_path), "duration": 60})()},
            )()

            result = VisualEnhancementAgent(
                executor=_Executor(),
                status_updater=lambda *args: updates.append(args),
                enhancement_service_factory=_Service,
            ).submit(
                VisualEnhancementRequest(
                    task_id="task-1",
                    note=note,
                    platform="bilibili",
                    enhance_token="enhance-1",
                    generation_token="generation-1",
                    gpt="vision-model",
                )
            )

        self.assertIs(result, future)
        self.assertEqual(updates, [])
        self.assertEqual(submitted[0][1][0], "task-1")
        self.assertEqual(submitted[0][1][1], str(video_path))
        self.assertEqual(submitted[0][1][2], 60)
        self.assertEqual(submitted[0][1][6], "vision-model")

    def test_visual_enhancement_agent_worker_failure_updates_status(self):
        updates = []

        class _Future:
            def add_done_callback(self, callback):
                callback(self)

            def result(self):
                raise RuntimeError("worker failed")

        class _Executor:
            def submit(self, *_args):
                return _Future()

        class _Service:
            def enhance_saved_note(self, *_args):
                return True

        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = pathlib.Path(tmp_dir) / "video.mp4"
            video_path.write_bytes(b"video")
            note = type(
                "_Note",
                (),
                {"audio_meta": type("_Meta", (), {"video_path": str(video_path), "duration": 60})()},
            )()

            VisualEnhancementAgent(
                executor=_Executor(),
                status_updater=lambda *args: updates.append(args),
                enhancement_service_factory=_Service,
            ).submit(
                VisualEnhancementRequest(
                    task_id="task-1",
                    note=note,
                    platform="bilibili",
                    enhance_token="enhance-1",
                    generation_token="generation-1",
                )
            )

        self.assertEqual(updates[0][0], "task-1")
        self.assertEqual(updates[0][3], TaskStatus.SUCCESS)
        self.assertIn("worker failed", updates[0][4])

    def test_execution_plan_keeps_screenshot_composer_background_when_deferred(self):
        plan = build_note_execution_plan(
            AgentExecutionContext(
                task_id="task-1",
                video_url="https://example.com/video",
                platform="bilibili",
                quality="medium",
                screenshot=True,
                defer_screenshots=True,
            )
        )

        compose = plan.get_step("compose_markdown")

        self.assertIsNotNone(compose)
        self.assertEqual(compose.mode, StepExecutionMode.BACKGROUND)

    def test_generate_treats_link_format_as_link_request_for_note_writer(self):
        captured = {}
        transcript = TranscriptResult(
            language="zh",
            full_text="hello",
            segments=[TranscriptSegment(start=0, end=1, text="hello")],
        )
        audio = AudioDownloadResult(
            file_path="audio.mp3",
            title="video",
            duration=60,
            cover_url="",
            platform="bilibili",
            video_id="video-1",
            raw_info={},
        )

        class _TranscriptAgent:
            def load_cached_or_platform_subtitles(self, **_kwargs):
                return transcript

        class _DownloadAgent:
            @staticmethod
            def needs_full_download(**_kwargs):
                return False

            def run(self, _request):
                return audio

        class _NoteWriterAgent:
            def run(self, request):
                captured["link"] = request.link
                captured["formats"] = request.formats
                return "## Note\n"

        with patch.object(NoteGenerator, "_init_transcriber", return_value=object()):
            generator = NoteGenerator(generation_token="generation-1")
        generator.transcript_agent = _TranscriptAgent()
        generator.download_agent = _DownloadAgent()
        generator.note_writer_agent = _NoteWriterAgent()

        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = pathlib.Path(tmp_dir)
            with (
                patch("app.services.note.NOTE_OUTPUT_DIR", output_dir),
                patch.object(generator, "_get_downloader", return_value=object()),
                patch.object(generator, "_get_gpt", return_value=object()),
                patch.object(generator, "_save_metadata", return_value=None),
            ):
                note = generator.generate(
                    video_url="https://example.com/video",
                    platform="bilibili",
                    quality="medium",
                    task_id="task-1",
                    model_name="model",
                    provider_id="provider",
                    link=False,
                    _format=["link"],
                    screenshot=False,
                    defer_screenshots=True,
                )

        self.assertIsNotNone(note)
        self.assertTrue(captured["link"])
        self.assertEqual(captured["formats"], ["link"])

    def test_cached_video_requires_screenshot_ready_resolution(self):
        from app.utils import video_quality

        with patch.object(video_quality, "probe_video_size", return_value=(852, 480)):
            self.assertFalse(video_quality.is_screenshot_ready_video(pathlib.Path("cached-480p.mp4")))

        with patch.object(video_quality, "probe_video_size", return_value=(1920, 1080)):
            self.assertTrue(video_quality.is_screenshot_ready_video(pathlib.Path("cached-1080p.mp4")))

    def test_cached_video_probe_failure_is_not_screenshot_ready(self):
        from app.utils import video_quality

        with patch.object(video_quality, "probe_video_size", return_value=None):
            self.assertFalse(video_quality.is_screenshot_ready_video(pathlib.Path("unknown.mp4")))


if __name__ == "__main__":
    unittest.main()
