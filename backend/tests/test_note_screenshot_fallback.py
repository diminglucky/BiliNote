import importlib.util
import json
import pathlib
import sys
import tempfile
import types
import unittest
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _install_stubs():
    app_mod = types.ModuleType("app")
    app_mod.__path__ = [str(ROOT / "app")]
    services_mod = types.ModuleType("app.services")
    services_mod.__path__ = [str(ROOT / "app" / "services")]
    utils_mod = types.ModuleType("app.utils")
    utils_mod.__path__ = [str(ROOT / "app" / "utils")]
    sys.modules["app"] = app_mod
    sys.modules["app.services"] = services_mod
    sys.modules["app.utils"] = utils_mod

    modules = {
        "fastapi": types.ModuleType("fastapi"),
        "pydantic": types.ModuleType("pydantic"),
        "dotenv": types.ModuleType("dotenv"),
        "app.downloaders": types.ModuleType("app.downloaders"),
        "app.downloaders.base": types.ModuleType("app.downloaders.base"),
        "app.downloaders.bilibili_downloader": types.ModuleType("app.downloaders.bilibili_downloader"),
        "app.downloaders.douyin_downloader": types.ModuleType("app.downloaders.douyin_downloader"),
        "app.downloaders.local_downloader": types.ModuleType("app.downloaders.local_downloader"),
        "app.downloaders.youtube_downloader": types.ModuleType("app.downloaders.youtube_downloader"),
        "app.db": types.ModuleType("app.db"),
        "app.db.video_task_dao": types.ModuleType("app.db.video_task_dao"),
        "app.enmus": types.ModuleType("app.enmus"),
        "app.enmus.exception": types.ModuleType("app.enmus.exception"),
        "app.enmus.task_status_enums": types.ModuleType("app.enmus.task_status_enums"),
        "app.enmus.note_enums": types.ModuleType("app.enmus.note_enums"),
        "app.exceptions": types.ModuleType("app.exceptions"),
        "app.exceptions.note": types.ModuleType("app.exceptions.note"),
        "app.exceptions.provider": types.ModuleType("app.exceptions.provider"),
        "app.gpt": types.ModuleType("app.gpt"),
        "app.gpt.base": types.ModuleType("app.gpt.base"),
        "app.gpt.gpt_factory": types.ModuleType("app.gpt.gpt_factory"),
        "app.models": types.ModuleType("app.models"),
        "app.models.audio_model": types.ModuleType("app.models.audio_model"),
        "app.models.gpt_model": types.ModuleType("app.models.gpt_model"),
        "app.models.model_config": types.ModuleType("app.models.model_config"),
        "app.models.notes_model": types.ModuleType("app.models.notes_model"),
        "app.models.transcriber_model": types.ModuleType("app.models.transcriber_model"),
        "app.services.constant": types.ModuleType("app.services.constant"),
        "app.services.provider": types.ModuleType("app.services.provider"),
        "app.transcriber": types.ModuleType("app.transcriber"),
        "app.transcriber.base": types.ModuleType("app.transcriber.base"),
        "app.transcriber.transcriber_provider": types.ModuleType("app.transcriber.transcriber_provider"),
        "app.utils.note_helper": types.ModuleType("app.utils.note_helper"),
        "app.utils.status_code": types.ModuleType("app.utils.status_code"),
        "app.utils.video_helper": types.ModuleType("app.utils.video_helper"),
        "app.utils.video_reader": types.ModuleType("app.utils.video_reader"),
    }

    for name, module in modules.items():
        sys.modules[name] = module

    modules["fastapi"].FastAPI = object
    modules["fastapi"].HTTPException = Exception
    modules["pydantic"].HttpUrl = str
    modules["dotenv"].load_dotenv = lambda *_args, **_kwargs: None
    modules["app.downloaders.base"].Downloader = object
    modules["app.downloaders.bilibili_downloader"].BilibiliDownloader = object
    modules["app.downloaders.douyin_downloader"].DouyinDownloader = object
    modules["app.downloaders.local_downloader"].LocalDownloader = object
    modules["app.downloaders.youtube_downloader"].YoutubeDownloader = object
    modules["app.db.video_task_dao"].delete_task_by_video = lambda *_args, **_kwargs: None
    modules["app.db.video_task_dao"].insert_video_task = lambda *_args, **_kwargs: None
    modules["app.enmus.exception"].NoteErrorEnum = object
    modules["app.enmus.exception"].ProviderErrorEnum = object
    modules["app.enmus.task_status_enums"].TaskStatus = object
    modules["app.enmus.note_enums"].DownloadQuality = type("DownloadQuality", (), {"medium": "medium"})
    modules["app.exceptions.note"].NoteError = Exception
    modules["app.exceptions.provider"].ProviderError = Exception
    modules["app.gpt.base"].GPT = object
    modules["app.gpt.gpt_factory"].GPTFactory = object
    modules["app.models.audio_model"].AudioDownloadResult = object
    modules["app.models.gpt_model"].GPTSource = object
    modules["app.models.model_config"].ModelConfig = object
    modules["app.models.notes_model"].AudioDownloadResult = object
    modules["app.models.notes_model"].NoteResult = object
    modules["app.models.transcriber_model"].TranscriptResult = object
    modules["app.models.transcriber_model"].TranscriptSegment = object
    modules["app.services.constant"].SUPPORT_PLATFORM_MAP = {}
    modules["app.services.provider"].ProviderService = object
    modules["app.transcriber.base"].Transcriber = object
    modules["app.transcriber.transcriber_provider"].get_transcriber = lambda *_args, **_kwargs: None
    modules["app.transcriber.transcriber_provider"]._transcribers = {}
    modules["app.utils.note_helper"].replace_content_markers = lambda markdown, **_kwargs: markdown
    modules["app.utils.note_helper"].prepend_source_link = lambda markdown, *_args, **_kwargs: markdown
    modules["app.utils.status_code"].StatusCode = object
    modules["app.utils.video_helper"].generate_screenshot = lambda *_args, **_kwargs: ""

    class _VideoReader:
        def __init__(self, *_args, **_kwargs):
            pass

        def extract_representative_timestamps(self):
            return []

    class _FrameCandidate:
        def __init__(self, path, timestamp, score, exact_hash, perceptual_hash=None):
            self.path = path
            self.timestamp = timestamp
            self.score = score
            self.exact_hash = exact_hash
            self.perceptual_hash = perceptual_hash

    modules["app.utils.video_reader"].FrameCandidate = _FrameCandidate
    modules["app.utils.video_reader"].VideoReader = _VideoReader


_install_stubs()


def _load_note_module():
    module_path = ROOT / "app" / "services" / "note.py"
    spec = importlib.util.spec_from_file_location("note_service", module_path)
    if spec is None or spec.loader is None:
        raise ImportError("note module spec not found")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


note_module = _load_note_module()
NoteGenerator = note_module.NoteGenerator
VisualScreenshotAgent = note_module.VisualScreenshotAgent
VisualScreenshotState = note_module.VisualScreenshotState


class TestNoteScreenshotFallback(unittest.TestCase):
    def test_fallback_uses_visual_timestamps_without_fixed_three_limit(self):
        expected = [12, 48, 110, 205]

        class _Reader:
            def __init__(self, *_args, **_kwargs):
                pass

            def extract_representative_timestamps(self):
                return expected

        generator = NoteGenerator.__new__(NoteGenerator)
        with patch.object(note_module, "VideoReader", _Reader):
            result = generator._fallback_screenshot_timestamps(pathlib.Path("video.mp4"), 600)

        self.assertEqual(result, expected)

    def test_fallback_uses_uniform_timestamps_only_when_visual_scan_fails(self):
        class _Reader:
            def __init__(self, *_args, **_kwargs):
                pass

            def extract_representative_timestamps(self):
                raise RuntimeError("scan failed")

        generator = NoteGenerator.__new__(NoteGenerator)
        with patch.object(note_module, "VideoReader", _Reader):
            result = generator._fallback_screenshot_timestamps(pathlib.Path("video.mp4"), 100)

        self.assertEqual(result, [20, 50, 80])

    def test_sampling_interval_grows_for_long_videos(self):
        self.assertEqual(NoteGenerator._fallback_sampling_interval(5 * 60), 6)
        self.assertGreater(NoteGenerator._fallback_sampling_interval(4 * 60 * 60), 20)

    def test_visual_agent_run_exposes_state(self):
        agent = VisualScreenshotAgent(image_output_dir=".", image_base_url="/static/screenshots")
        markdown = (
            "## 背景说明 *Content-[00:10]\n"
            "这里只讲背景和目标，不需要截图。\n"
        )
        state = VisualScreenshotState(markdown=markdown, video_path=pathlib.Path("video.mp4"), duration=120)

        result = agent.run(state)

        self.assertIs(result, state)
        self.assertEqual(state.markdown, markdown)
        self.assertEqual(state.matches, [])
        self.assertEqual(state.visual_plans, [])
        self.assertEqual(state.generated_images, [])
        self.assertEqual(state.diagnostics, [])

    def test_fallback_images_are_inserted_near_content_sections(self):
        generator = NoteGenerator.__new__(NoteGenerator)
        markdown = (
            "## 第一部分 *Content-[00:10]\n"
            "这里讲第一部分。\n\n"
            "## 第二部分 *Content-[01:00]\n"
            "这里讲第二部分。\n"
        )

        result = generator._insert_fallback_images_near_sections(
            markdown,
            [(12, "![](/static/screenshots/a.jpg)"), (70, "![](/static/screenshots/b.jpg)")],
        )

        self.assertLess(
            result.index("![](/static/screenshots/a.jpg)"),
            result.index("## 第二部分"),
        )
        self.assertGreater(
            result.index("![](/static/screenshots/b.jpg)"),
            result.index("## 第二部分"),
        )
        self.assertNotIn("## 原片截图", result)

    def test_fallback_images_append_when_content_markers_are_missing(self):
        generator = NoteGenerator.__new__(NoteGenerator)

        result = generator._insert_fallback_images_near_sections(
            "## 无时间线\n正文",
            [(12, "![](/static/screenshots/a.jpg)")],
        )

        self.assertIn("## 原片截图", result)
        self.assertTrue(result.rstrip().endswith("![](/static/screenshots/a.jpg)"))

    def test_structural_planner_selects_visual_sections(self):
        generator = NoteGenerator.__new__(NoteGenerator)
        markdown = (
            "## Background *Content-[00:10]\n"
            "This section only introduces definitions.\n\n"
            "## Architecture diagram *Content-[01:00]\n"
            "The diagram shows the Agent, Tool, and MCP relationship. This flow chart needs a visual.\n\n"
            "## AI Summary *Content-[03:00]\n"
            "A short text summary.\n"
        )

        plans = generator._plan_visual_screenshots(markdown, 240)

        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0].title, "Architecture diagram")
        self.assertGreater(plans[0].score, 2)

    def test_content_markers_ignore_toc_links_when_headings_exist(self):
        markdown = (
            "## 目录\n"
            "- [Plan and Execute *Content-[20:24]](#plan-and-execute)\n\n"
            "## Plan and Execute *Content-[20:24]\n"
            "This flow diagram explains a plan model, replan model, execution agent, and UI result.\n"
        )

        markers = NoteGenerator._content_line_markers(markdown)

        self.assertEqual(markers, [(3, 1224)])

    def test_structural_planner_skips_text_only_notes(self):
        generator = NoteGenerator.__new__(NoteGenerator)
        markdown = (
            "## Background *Content-[00:10]\n"
            "This section explains history and basic definitions.\n\n"
            "## Summary *Content-[01:00]\n"
            "The final section lists a few text-only points.\n"
        )

        plans = generator._plan_visual_screenshots(markdown, 120)

        self.assertEqual(plans, [])

    def test_structural_planner_can_infer_times_from_screenshot_markers(self):
        generator = NoteGenerator.__new__(NoteGenerator)
        markdown = (
            "## Plain background\n"
            "*Screenshot-[00:10]\n"
            "This section is text-only background.\n\n"
            "## Flow diagram\n"
            "*Screenshot-[01:00]\n"
            "*Screenshot-[01:20]\n"
            "This flow diagram explains the tool calling process.\n"
        )

        plans = generator._plan_visual_screenshots(markdown, 180)

        self.assertEqual(len(plans), 1)
        self.assertEqual(plans[0].title, "Flow diagram")
        self.assertGreaterEqual(plans[0].start, 60)

    def test_screenshot_marker_text_does_not_count_as_visual_keyword(self):
        score, reasons = NoteGenerator._visual_keyword_score(
            "Only a generated marker appears here: *Screenshot-[00:10]*"
        )

        self.assertEqual(score, 0)
        self.assertEqual(reasons, [])

    def test_structure_filter_keeps_one_marker_per_visual_section(self):
        generator = NoteGenerator.__new__(NoteGenerator)
        markdown = (
            "## Code walkthrough\n"
            "*Screenshot-[01:00]\n"
            "*Screenshot-[01:20]\n"
            "*Screenshot-[01:40]\n"
            "This code demo explains a command and its running result.\n"
        )
        matches = generator._extract_screenshot_timestamps(markdown)
        plans = generator._plan_visual_screenshots(markdown, 180)

        filtered_markdown, filtered = generator._filter_screenshot_matches_by_structure(
            markdown,
            matches,
            plans,
        )

        self.assertEqual(len(plans), 1)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered_markdown.count("Screenshot-"), 1)

    def test_dense_visual_section_can_keep_multiple_markers(self):
        generator = NoteGenerator.__new__(NoteGenerator)
        markdown = (
            "## Dense implementation walkthrough *Content-[00:00]\n"
            "*Screenshot-[01:00]\n"
            "*Screenshot-[02:00]\n"
            "*Screenshot-[03:00]\n"
            "*Screenshot-[04:00]\n"
            "*Screenshot-[05:00]\n"
            "This architecture diagram explains a flow, table, screen, formula, code demo, and UI result.\n"
            "```python\nprint('step one')\n```\n"
            "```bash\npython app.py\n```\n\n"
            "## Next section *Content-[10:00]\n"
            "Plain text.\n"
        )
        matches = generator._extract_screenshot_timestamps(markdown)
        plans = generator._plan_visual_screenshots(markdown, 900)

        filtered_markdown, filtered = generator._filter_screenshot_matches_by_structure(
            markdown,
            matches,
            plans,
        )

        self.assertGreaterEqual(len(plans), 3)
        self.assertGreaterEqual(len(filtered), 3)
        self.assertLess(len(filtered), len(matches))
        self.assertGreaterEqual(filtered_markdown.count("Screenshot-"), 3)

    def test_long_step_section_with_subsections_gets_multiple_plans(self):
        generator = NoteGenerator.__new__(NoteGenerator)
        markdown = (
            "## Plan and Execute 模式详解 *Content-[20:24]\n"
            "这是一段流程演示，说明 plan model、replan model、execution agent 的步骤。\n\n"
            "### 核心角色\n"
            "1. Plan Model：制定计划。\n"
            "2. Replan Model：更新计划。\n"
            "3. Execution Agent：执行步骤。\n\n"
            "### 示例\n"
            "- Step 1: 查询当前日期。\n"
            "- Step 2: 查询冠军名字。\n"
            "- Step 3: 查询家乡并输出结果。\n\n"
            "## 下一节 *Content-[27:49]\n"
            "普通总结。"
        )

        plans = generator._plan_visual_screenshots(markdown, 1800)

        plan_section = [plan for plan in plans if plan.title == "Plan and Execute 模式详解"]
        self.assertGreaterEqual(len(plan_section), 2)
        self.assertLess(plan_section[0].end, plan_section[1].end)

    def test_explicit_screenshot_markers_drop_duplicate_visuals(self):
        generator = NoteGenerator.__new__(NoteGenerator)

        class _Reader:
            def __init__(self, *_args, **_kwargs):
                pass

            @staticmethod
            def _calculate_file_md5(_path):
                return "different-file"

            @staticmethod
            def _score_frame(_path):
                return 0.9, 123

            @staticmethod
            def _is_same_visual_state(_left, _right):
                return True

        with tempfile.TemporaryDirectory() as tmp_dir:
            created = []

            def _generate(_video_path, _output_dir, _timestamp, index):
                path = pathlib.Path(tmp_dir) / f"shot_{index}.jpg"
                path.write_bytes(b"image")
                created.append(path)
                return str(path)

            with patch.object(note_module, "IMAGE_OUTPUT_DIR", pathlib.Path(tmp_dir)), \
                    patch.object(note_module, "VideoReader", _Reader), \
                    patch.object(note_module, "generate_screenshot", side_effect=_generate):
                result = generator._insert_screenshots(
                    (
                        "## UI demo *Content-[00:00]\n"
                        "This screen demo shows a UI and code walkthrough.\n"
                        "A *Screenshot-[00:10]\nB *Screenshot-[00:20]"
                    ),
                    pathlib.Path("video.mp4"),
                    60,
                )

            self.assertEqual(result.count("![]("), 1)
            kept = [path for path in created if path.exists()]
            self.assertEqual(len(kept), 1)

    def test_explicit_screenshot_markers_outside_visual_sections_are_removed(self):
        generator = NoteGenerator.__new__(NoteGenerator)

        def _generate(*_args, **_kwargs):
            raise AssertionError("Screenshot should not be generated for text-only sections")

        markdown = (
            "## Background *Content-[00:00]\n"
            "This section explains history and definitions only. *Screenshot-[00:10]\n"
        )

        with patch.object(note_module, "generate_screenshot", side_effect=_generate):
            result = generator._insert_screenshots(markdown, pathlib.Path("video.mp4"), 60)

        self.assertNotIn("*Screenshot", result)
        self.assertNotIn("![](", result)

    def test_best_screenshot_searches_forward_to_capture_final_state(self):
        generator = NoteGenerator.__new__(NoteGenerator)

        class _Reader:
            @staticmethod
            def _calculate_file_md5(path):
                return pathlib.Path(path).name

            @staticmethod
            def _score_frame(path):
                timestamp = int(pathlib.Path(path).stem.split("_")[-1])
                if timestamp >= 40:
                    return 0.9, timestamp
                return 0.35, timestamp

        with tempfile.TemporaryDirectory() as tmp_dir:
            created = []

            def _generate(_video_path, _output_dir, timestamp, index):
                path = pathlib.Path(tmp_dir) / f"shot_{index}_{timestamp}.jpg"
                path.write_bytes(f"image-{timestamp}".encode())
                created.append(path)
                return str(path)

            with patch.object(note_module, "IMAGE_OUTPUT_DIR", pathlib.Path(tmp_dir)), \
                    patch.object(note_module, "generate_screenshot", side_effect=_generate):
                candidate = generator._best_screenshot_near_timestamp(
                    video_path=pathlib.Path("video.mp4"),
                    timestamp=0,
                    duration=120,
                    index=0,
                    visual_reader=_Reader(),
                    search_end=60,
                )

            self.assertIsNotNone(candidate)
            self.assertGreaterEqual(candidate.timestamp, 40)
            self.assertTrue(pathlib.Path(candidate.path).exists())
            self.assertEqual([path for path in created if path.exists()], [pathlib.Path(candidate.path)])

    def test_best_screenshot_prefers_stable_frame_over_one_off_transition(self):
        generator = NoteGenerator.__new__(NoteGenerator)

        class _Reader:
            @staticmethod
            def _calculate_file_md5(path):
                return pathlib.Path(path).name

            @staticmethod
            def _score_frame(path):
                timestamp = int(pathlib.Path(path).stem.split("_")[-1])
                if timestamp == 22:
                    return 0.96, 1000
                if timestamp in {34, 45, 50}:
                    return 0.84, 2000
                return 0.25, timestamp

            @staticmethod
            def _build_visual_segments(candidates):
                by_ts = {candidate.timestamp: candidate for candidate in candidates}
                class _Segment:
                    def __init__(self, start, end, representative, frames):
                        self.start = start
                        self.end = end
                        self.representative = representative
                        self.frames = frames

                    @property
                    def duration(self):
                        return max(0, self.end - self.start)

                return [
                    _Segment(22, 22, by_ts[22], [by_ts[22]]),
                    _Segment(34, 50, by_ts[45], [by_ts[34], by_ts[45], by_ts[50]]),
                ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            created = []

            def _generate(_video_path, _output_dir, timestamp, index):
                path = pathlib.Path(tmp_dir) / f"shot_{index}_{timestamp}.jpg"
                path.write_bytes(f"image-{timestamp}".encode())
                created.append(path)
                return str(path)

            with patch.object(note_module, "IMAGE_OUTPUT_DIR", pathlib.Path(tmp_dir)), \
                    patch.object(note_module, "generate_screenshot", side_effect=_generate):
                candidate = generator._best_screenshot_near_timestamp(
                    video_path=pathlib.Path("video.mp4"),
                    timestamp=0,
                    duration=120,
                    index=0,
                    visual_reader=_Reader(),
                    search_end=60,
                )

            self.assertIsNotNone(candidate)
            self.assertEqual(candidate.timestamp, 45)
            self.assertEqual([path for path in created if path.exists()], [pathlib.Path(candidate.path)])

    def test_best_screenshot_prefers_later_complete_state_when_quality_is_close(self):
        generator = NoteGenerator.__new__(NoteGenerator)

        class _Reader:
            @staticmethod
            def _calculate_file_md5(path):
                return pathlib.Path(path).name

            @staticmethod
            def _score_frame(path):
                timestamp = int(pathlib.Path(path).stem.split("_")[-1])
                if timestamp == 22:
                    return 0.90, 1000
                if timestamp in {60, 90, 118}:
                    return 0.78, 2000
                return 0.30, timestamp

            @staticmethod
            def _build_visual_segments(candidates):
                by_ts = {candidate.timestamp: candidate for candidate in candidates}

                class _Segment:
                    def __init__(self, start, end, representative, frames):
                        self.start = start
                        self.end = end
                        self.representative = representative
                        self.frames = frames

                    @property
                    def duration(self):
                        return max(0, self.end - self.start)

                return [
                    _Segment(22, 22, by_ts[22], [by_ts[22]]),
                    _Segment(60, 118, by_ts[90], [by_ts[60], by_ts[90], by_ts[118]]),
                ]

        with tempfile.TemporaryDirectory() as tmp_dir:
            created = []

            def _generate(_video_path, _output_dir, timestamp, index):
                path = pathlib.Path(tmp_dir) / f"shot_{index}_{timestamp}.jpg"
                path.write_bytes(f"image-{timestamp}".encode())
                created.append(path)
                return str(path)

            with patch.object(note_module, "IMAGE_OUTPUT_DIR", pathlib.Path(tmp_dir)), \
                    patch.object(note_module, "generate_screenshot", side_effect=_generate):
                candidate = generator._best_screenshot_near_timestamp(
                    video_path=pathlib.Path("video.mp4"),
                    timestamp=0,
                    duration=160,
                    index=0,
                    visual_reader=_Reader(),
                    search_end=120,
                )

            self.assertIsNotNone(candidate)
            self.assertEqual(candidate.timestamp, 90)
            self.assertEqual([path for path in created if path.exists()], [pathlib.Path(candidate.path)])

    def test_multimodal_reviewer_can_choose_better_candidate(self):
        generator = NoteGenerator.__new__(NoteGenerator)

        class _Message:
            content = json.dumps({"selected": 1, "reason": "后面的截图包含最终结果", "confidence": 0.9})

        class _Choice:
            message = _Message()

        class _Completions:
            def create(self, **kwargs):
                self.kwargs = kwargs
                return type("_Response", (), {"choices": [_Choice()]})()

        class _Chat:
            def __init__(self):
                self.completions = _Completions()

        class _Client:
            def __init__(self):
                self.chat = _Chat()

        class _Gpt:
            supports_vision = True
            model = "qwen-vl"

            def __init__(self):
                self.client = _Client()

        with tempfile.TemporaryDirectory() as tmp_dir:
            first = pathlib.Path(tmp_dir) / "first.jpg"
            second = pathlib.Path(tmp_dir) / "second.jpg"
            first.write_bytes(b"first")
            second.write_bytes(b"second")
            candidates = [
                note_module.FrameCandidate(str(first), 10, 0.95, "first", 1),
                note_module.FrameCandidate(str(second), 40, 0.75, "second", 2),
            ]

            chosen = generator._review_screenshot_candidates(
                candidates,
                _Gpt(),
                section_title="Plan and Execute",
                section_context="需要选择包含最终结果的截图。",
            )

        self.assertIsNotNone(chosen)
        self.assertEqual(chosen.timestamp, 40)

    def test_multimodal_reviewer_is_skipped_for_text_model(self):
        generator = NoteGenerator.__new__(NoteGenerator)

        class _Gpt:
            supports_vision = False

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = pathlib.Path(tmp_dir) / "frame.jpg"
            path.write_bytes(b"frame")
            candidates = [note_module.FrameCandidate(str(path), 10, 0.9, "a", 1)]

            chosen = generator._review_screenshot_candidates(candidates, _Gpt())

        self.assertIsNone(chosen)

    def test_best_screenshot_does_not_cross_before_section_start(self):
        generator = NoteGenerator.__new__(NoteGenerator)

        class _Reader:
            @staticmethod
            def _calculate_file_md5(path):
                return pathlib.Path(path).name

            @staticmethod
            def _score_frame(path):
                timestamp = int(pathlib.Path(path).stem.split("_")[-1])
                return (0.95 if timestamp < 100 else 0.7), timestamp

        with tempfile.TemporaryDirectory() as tmp_dir:
            captured_timestamps = []

            def _generate(_video_path, _output_dir, timestamp, index):
                path = pathlib.Path(tmp_dir) / f"shot_{index}_{timestamp}.jpg"
                path.write_bytes(f"image-{timestamp}".encode())
                captured_timestamps.append(timestamp)
                return str(path)

            with patch.object(note_module, "IMAGE_OUTPUT_DIR", pathlib.Path(tmp_dir)), \
                    patch.object(note_module, "generate_screenshot", side_effect=_generate):
                candidate = generator._best_screenshot_near_timestamp(
                    video_path=pathlib.Path("video.mp4"),
                    timestamp=100,
                    duration=200,
                    index=0,
                    visual_reader=_Reader(),
                    search_end=140,
                )

            self.assertIsNotNone(candidate)
            self.assertTrue(all(ts >= 100 for ts in captured_timestamps))
            self.assertGreaterEqual(candidate.timestamp, 100)


if __name__ == "__main__":
    unittest.main()
