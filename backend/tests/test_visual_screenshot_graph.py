import importlib.util
import os
import pathlib
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _load_visual_screenshot_graph():
    module_path = ROOT / "app" / "services" / "visual_screenshot_graph.py"
    spec = importlib.util.spec_from_file_location("visual_screenshot_graph", module_path)
    if spec is None or spec.loader is None:
        raise ImportError("visual_screenshot_graph module spec not found")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


visual_screenshot_graph = _load_visual_screenshot_graph()


class TestVisualScreenshotGraph(unittest.TestCase):
    def test_build_visual_screenshot_graph(self):
        graph = visual_screenshot_graph.build_visual_screenshot_graph()
        self.assertTrue(hasattr(graph, "invoke"))

    def test_real_langgraph_path_runs_agent_state(self):
        from app.services.visual_screenshot_agent import VisualScreenshotAgent, VisualScreenshotState

        agent = VisualScreenshotAgent(".", "/static/screenshots")
        state = VisualScreenshotState(
            markdown="## 背景说明 *Content-[00:10]\n这里只讲背景和目标，不需要截图。\n",
            video_path=pathlib.Path("video.mp4"),
            duration=120,
        )

        result = agent.run(state)

        self.assertIs(result, state)
        self.assertEqual(state.execution_engine, "langgraph")
        self.assertEqual(state.diagnostics, [])

    def test_real_langgraph_path_inserts_screenshot(self):
        from app.services.visual_screenshot_agent import VisualScreenshotAgent, VisualScreenshotState

        class _Reader:
            def __init__(self, *_args, **_kwargs):
                pass

            @staticmethod
            def _calculate_file_md5(path):
                return pathlib.Path(path).name

            @staticmethod
            def _score_frame(_path):
                return 0.92, 123

            @staticmethod
            def _is_same_visual_state(_left, _right):
                return False

        with tempfile.TemporaryDirectory() as tmp_dir:
            def _generate(_video_path, _output_dir, _timestamp, index):
                path = pathlib.Path(tmp_dir) / f"shot_{index}.jpg"
                path.write_bytes(b"image")
                return str(path)

            agent = VisualScreenshotAgent(
                image_output_dir=tmp_dir,
                image_base_url="/static/screenshots",
                video_reader_cls=_Reader,
                screenshot_func=_generate,
            )
            state = VisualScreenshotState(
                markdown=(
                    "## UI demo *Content-[00:00]\n"
                    "This screen demo shows a UI, code, page, and final result.\n"
                    "*Screenshot-[00:10]\n"
                ),
                video_path=pathlib.Path("video.mp4"),
                duration=60,
            )

            result = agent.run(state)

        self.assertIs(result, state)
        self.assertEqual(state.execution_engine, "langgraph")
        self.assertIn("![](/static/screenshots/", state.markdown)
        self.assertNotIn("*Screenshot", state.markdown)
        self.assertEqual(len(state.generated_images), 1)
        self.assertEqual(state.diagnostics, [])

    def test_real_langgraph_path_cleans_generated_files_on_failure(self):
        from app.services.visual_screenshot_agent import VisualScreenshotAgent, VisualScreenshotState
        visual_agent_module = sys.modules["app.services.visual_screenshot_agent"]

        class _Reader:
            def __init__(self, *_args, **_kwargs):
                pass

            @staticmethod
            def _calculate_file_md5(path):
                return pathlib.Path(path).name

            @staticmethod
            def _score_frame(_path):
                return 0.92, 123

            @staticmethod
            def _is_same_visual_state(_left, _right):
                return False

        with tempfile.TemporaryDirectory() as tmp_dir:
            created = []

            def _generate(_video_path, _output_dir, _timestamp, index):
                path = pathlib.Path(tmp_dir) / f"shot_{index}.jpg"
                path.write_bytes(b"image")
                created.append(path)
                return str(path)

            agent = VisualScreenshotAgent(
                image_output_dir=tmp_dir,
                image_base_url="/static/screenshots",
                video_reader_cls=_Reader,
                screenshot_func=_generate,
            )
            state = VisualScreenshotState(
                markdown=(
                    "## UI demo *Content-[00:00]\n"
                    "This screen demo shows a UI, code, page, and final result.\n"
                    "*Screenshot-[00:10]\n"
                ),
                video_path=pathlib.Path("video.mp4"),
                duration=60,
            )

            def _run_then_fail(agent_arg, state_arg):
                state_arg = agent_arg.prepare_state(state_arg)
                state_arg = agent_arg.filter_marker_node(state_arg)
                agent_arg.compose_images_node(state_arg)
                raise RuntimeError("boom")

            with patch.object(visual_agent_module, "run_visual_screenshot_graph", side_effect=_run_then_fail):
                with self.assertRaisesRegex(RuntimeError, "boom"):
                    agent.run(state)

        self.assertTrue(created)
        self.assertTrue(all(not path.exists() for path in created))
        self.assertEqual(state.execution_engine, "langgraph")

    def test_real_langgraph_path_keeps_incrementally_published_images_on_later_failure(self):
        from app.services.visual_screenshot_agent import VisualScreenshotAgent, VisualScreenshotState

        class _Reader:
            def __init__(self, *_args, **_kwargs):
                pass

            @staticmethod
            def _calculate_file_md5(path):
                return pathlib.Path(path).name

            @staticmethod
            def _score_frame(path):
                if "fail" in pathlib.Path(path).name:
                    raise RuntimeError("score failed")
                return 0.92, pathlib.Path(path).name

            @staticmethod
            def _is_same_visual_state(_left, _right):
                return False

        with tempfile.TemporaryDirectory() as tmp_dir:
            created = []
            published = []

            def _generate(_video_path, _output_dir, timestamp, index):
                label = "fail" if index >= 10 else "ok"
                path = pathlib.Path(tmp_dir) / f"{label}_{index}_{timestamp}.jpg"
                path.write_bytes(b"image")
                created.append(path)
                return str(path)

            def _on_update(markdown_snapshot, _timestamp, _image_markdown):
                published.append(markdown_snapshot)

            agent = VisualScreenshotAgent(
                image_output_dir=tmp_dir,
                image_base_url="/static/screenshots",
                video_reader_cls=_Reader,
                screenshot_func=_generate,
            )
            state = VisualScreenshotState(
                markdown=(
                    "## First visual *Content-[00:00]\n"
                    "This screen demo shows a UI, code, page, and final result.\n"
                    "*Screenshot-[00:00]\n\n"
                    "## Second visual *Content-[01:00]\n"
                    "This screen demo shows another UI, code, page, and final result.\n"
                    "*Screenshot-[01:00]\n"
                ),
                video_path=pathlib.Path("video.mp4"),
                duration=120,
                on_markdown_update=_on_update,
            )

            result = agent.run(state)

            failed_files = [path for path in created if "fail_" in path.name]
            published_files = [pathlib.Path(path) for path in state.published_image_paths or []]
            self.assertTrue(published)
            self.assertTrue(published_files)
            self.assertTrue(all(path.exists() for path in published_files))
            self.assertTrue(all(not path.exists() for path in failed_files))
            self.assertIs(result, state)
            self.assertNotIn("*Screenshot", state.markdown)
            self.assertIn("score failed", "\n".join(state.diagnostics or []))

    def test_dynamic_slot_workflow_isolates_individual_slot_failure(self):
        from app.services.visual_screenshot_agent import VisualScreenshotAgent, VisualScreenshotState

        class _Reader:
            def __init__(self, *_args, **_kwargs):
                pass

            @staticmethod
            def _calculate_file_md5(path):
                return pathlib.Path(path).name

            @staticmethod
            def _score_frame(path):
                candidate_index = int(pathlib.Path(path).stem.split("_")[1])
                if candidate_index >= 10:
                    raise RuntimeError("second slot failed")
                return 0.92, pathlib.Path(path).name

            @staticmethod
            def _is_same_visual_state(_left, _right):
                return False

        with tempfile.TemporaryDirectory() as tmp_dir:
            def _generate(_video_path, _output_dir, timestamp, index):
                path = pathlib.Path(tmp_dir) / f"slot_{index}_{timestamp}.jpg"
                path.write_bytes(f"image-{timestamp}".encode())
                return str(path)

            agent = VisualScreenshotAgent(
                image_output_dir=tmp_dir,
                image_base_url="/static/screenshots",
                video_reader_cls=_Reader,
                screenshot_func=_generate,
            )
            state = VisualScreenshotState(
                markdown=(
                    "## First visual *Content-[00:00]\n"
                    "This screen demo shows a UI, code, page, and final result.\n"
                    "*Screenshot-[00:10]\n\n"
                    "## Second visual *Content-[01:00]\n"
                    "This screen demo shows another UI, code, page, and final result.\n"
                    "*Screenshot-[01:10]\n"
                ),
                video_path=pathlib.Path("video.mp4"),
                duration=120,
            )

            result = agent.run(state)

        self.assertIs(result, state)
        self.assertEqual(state.execution_engine, "langgraph")
        self.assertEqual(state.markdown.count("![]("), 1)
        self.assertNotIn("*Screenshot", state.markdown)
        self.assertIn("second slot failed", "\n".join(state.diagnostics or []))

    def test_dynamic_slot_workflow_respects_balanced_vision_review_budget(self):
        from app.services.visual_screenshot_agent import VisualScreenshotAgent, VisualScreenshotState

        class _Reader:
            def __init__(self, *_args, **_kwargs):
                pass

            @staticmethod
            def _calculate_file_md5(path):
                return pathlib.Path(path).name

            @staticmethod
            def _score_frame(path):
                timestamp = int(pathlib.Path(path).stem.split("_")[-1])
                return (0.82 if timestamp < 40 else 0.78), timestamp

            @staticmethod
            def _is_same_visual_state(_left, _right):
                return False

        class _Gpt:
            supports_vision = True
            model = "qwen-vl"
            client = object()

        with tempfile.TemporaryDirectory() as tmp_dir:
            review_calls = []

            def _generate(_video_path, _output_dir, timestamp, index):
                path = pathlib.Path(tmp_dir) / f"slot_{index}_{timestamp}.jpg"
                path.write_bytes(f"image-{timestamp}".encode())
                return str(path)

            def _review(_self, candidates, *_args, **_kwargs):
                review_calls.append(candidates)
                return max(candidates, key=lambda item: item.timestamp)

            agent = VisualScreenshotAgent(
                image_output_dir=tmp_dir,
                image_base_url="/static/screenshots",
                video_reader_cls=_Reader,
                screenshot_func=_generate,
            )
            state = VisualScreenshotState(
                markdown=(
                    "## Plan-And-Execute Agent *Content-[00:00]\n"
                    "This UI needs the complete Plan and Execute final result screen.\n"
                    "*Screenshot-[00:00]\n\n"
                    "## Second Agent workflow *Content-[01:00]\n"
                    "This UI also needs the complete Plan and Execute final result screen.\n"
                    "*Screenshot-[01:00]\n"
                ),
                video_path=pathlib.Path("video.mp4"),
                duration=120,
                gpt=_Gpt(),
            )

            with patch.dict(
                os.environ,
                {
                    "SCREENSHOT_REVIEW_MODE": "balanced",
                    "SCREENSHOT_VISION_REVIEW_LIMIT": "1",
                },
                clear=False,
            ), patch.object(
                VisualScreenshotAgent,
                "review_screenshot_candidates",
                _review,
            ):
                result = agent.run(state)

        self.assertIs(result, state)
        self.assertEqual(len(review_calls), 1)
        self.assertEqual(agent._vision_review_count, 1)
        self.assertEqual(state.markdown.count("![]("), 2)

    def test_dynamic_slot_workflow_limits_slot_concurrency(self):
        from app.services.visual_screenshot_agent import VisualScreenshotAgent, VisualScreenshotState

        class _Reader:
            def __init__(self, *_args, **_kwargs):
                pass

            @staticmethod
            def _calculate_file_md5(path):
                return pathlib.Path(path).name

            @staticmethod
            def _score_frame(_path):
                return 0.92, 123

            @staticmethod
            def _is_same_visual_state(_left, _right):
                return False

        with tempfile.TemporaryDirectory() as tmp_dir:
            active = 0
            max_active = 0
            lock = threading.Lock()

            def _generate(_video_path, _output_dir, timestamp, index):
                nonlocal active, max_active
                with lock:
                    active += 1
                    max_active = max(max_active, active)
                try:
                    time.sleep(0.03)
                    path = pathlib.Path(tmp_dir) / f"slot_{index}_{timestamp}.jpg"
                    path.write_bytes(f"image-{timestamp}".encode())
                    return str(path)
                finally:
                    with lock:
                        active -= 1

            markdown = "\n\n".join(
                [
                    (
                        f"## Visual section {idx} *Content-[0{idx}:00]\n"
                        "This screen demo shows UI, code, page, and final result.\n"
                        f"*Screenshot-[0{idx}:05]"
                    )
                    for idx in range(4)
                ]
            )
            with patch.dict(os.environ, {"SCREENSHOT_SLOT_CONCURRENCY": "2"}, clear=False):
                agent = VisualScreenshotAgent(
                    image_output_dir=tmp_dir,
                    image_base_url="/static/screenshots",
                    video_reader_cls=_Reader,
                    screenshot_func=_generate,
                )
                state = VisualScreenshotState(
                    markdown=markdown,
                    video_path=pathlib.Path("video.mp4"),
                    duration=360,
                )

                result = agent.run(state)

        self.assertIs(result, state)
        self.assertLessEqual(max_active, 2)

    def test_prepare_state_normalizes_plural_screenshot_markers(self):
        from app.services.visual_screenshot_agent import VisualScreenshotAgent, VisualScreenshotState

        agent = VisualScreenshotAgent(".", "/static/screenshots")
        state = VisualScreenshotState(
            markdown="## Demo\nScreenshots-[04:16], [04:44], [05:12]",
            video_path=pathlib.Path("video.mp4"),
            duration=360,
        )

        agent.prepare_state(state)

        self.assertNotIn("Screenshots-", state.markdown)
        self.assertEqual(
            state.matches,
            [
                ("*Screenshot-[04:16]", 256),
                ("*Screenshot-[04:44]", 284),
                ("*Screenshot-[05:12]", 312),
            ],
        )

    def test_supplemental_budget_comes_from_visual_content_not_duration(self):
        from app.services.visual_screenshot_agent import VisualSectionPlan, screenshot_content_budget

        plans = [
            VisualSectionPlan(
                title="One useful screen",
                start=60,
                end=120,
                score=5.0,
                reasons=["screen"],
                line_index=1,
                insert_line=2,
            )
        ]

        self.assertEqual(screenshot_content_budget(plans), 1)

    def test_section_analyzer_reads_markdown_before_planning_images(self):
        from app.services.visual_screenshot_agent import VisualScreenshotAgent

        markdown = (
            "## Concept only *Content-[00:00]\n"
            "This section explains history and definitions only.\n\n"
            "## Code result walkthrough *Content-[02:00]\n"
            "The screen shows code, command output, UI result, and final page.\n"
            "```bash\npython app.py\n```\n"
            "1. Open the settings page\n"
            "2. Run the command\n"
            "3. Check the final result\n"
        )
        agent = VisualScreenshotAgent(".", "/static/screenshots")

        analyses = agent.analyze_markdown_sections(markdown, 420)

        self.assertEqual(len(analyses), 1)
        self.assertEqual(analyses[0].title, "Code result walkthrough")
        self.assertGreaterEqual(analyses[0].suggested_count, 2)
        self.assertIn("code-block", analyses[0].reasons)
        self.assertTrue(analyses[0].insert_lines)

    def test_section_analyzer_uses_transcript_alignment_when_content_marker_is_missing(self):
        from app.services.visual_screenshot_agent import VisualScreenshotAgent

        markdown = (
            "## UI 操作演示\n"
            "这里演示设置页、代码和运行结果。\n\n"
            "## 另一个章节\n"
            "这里只是背景说明。\n"
        )
        transcript_segments = [
            {"start": 12, "end": 18, "text": "这里打开设置页"},
            {"start": 18, "end": 30, "text": "然后展示运行结果和页面"},
            {"start": 90, "end": 98, "text": "这里是背景说明"},
        ]
        agent = VisualScreenshotAgent(".", "/static/screenshots")

        analyses = agent.analyze_markdown_sections(markdown, 180, transcript_segments=transcript_segments)

        self.assertEqual(len(analyses), 1)
        self.assertEqual(analyses[0].title, "UI 操作演示")
        self.assertLessEqual(analyses[0].start, 18)
        self.assertIn("transcript-align", analyses[0].reasons)

    def test_document_planner_places_image_after_relevant_line(self):
        from app.services.visual_screenshot_agent import VisualScreenshotAgent

        markdown = (
            "## 工具安装 *Content-[00:00]\n"
            "先介绍工具背景。\n"
            "运行安装命令并检查终端输出。\n"
            "```bash\n"
            "pnpm install\n"
            "```\n"
            "最终页面显示安装成功。\n\n"
            "## 纯概念说明 *Content-[02:00]\n"
            "这里只讲背景和定义。\n"
        )
        agent = VisualScreenshotAgent(".", "/static/screenshots")

        plans = agent.plan_visual_screenshots(markdown, 180)

        self.assertTrue(plans)
        self.assertTrue(all(plan.insert_line is not None for plan in plans))
        self.assertTrue(any(3 <= int(plan.insert_line or 0) <= 7 for plan in plans))

    def test_insert_images_at_document_lines_uses_planned_positions(self):
        from app.services.visual_screenshot_agent import VisualScreenshotAgent

        markdown = (
            "## 工具安装 *Content-[00:00]\n"
            "先介绍工具背景。\n"
            "运行安装命令并检查终端输出。\n"
            "```bash\n"
            "pnpm install\n"
            "```\n"
            "最终页面显示安装成功。\n\n"
            "## 下一节 *Content-[02:00]\n"
            "下一节正文。\n"
        )

        result = VisualScreenshotAgent.insert_images_at_document_lines(
            markdown,
            [(6, "![](/static/screenshots/install.jpg)")],
        )

        self.assertLess(result.index("install.jpg"), result.index("最终页面显示安装成功"))
        self.assertLess(result.index("install.jpg"), result.index("## 下一节"))

    def test_plan_visual_screenshots_prefers_explicit_markers_over_duration(self):
        from app.services.visual_screenshot_agent import VisualScreenshotAgent

        markdown = (
            "## Intro *Content-[00:10]\n"
            "This section gives background and a demo screenshot hint.\n"
            "*Screenshot-[00:20]\n\n"
            "## Deep dive *Content-[02:00]\n"
            "This section shows code, UI, result, and final workflow.\n"
            "*Screenshot-[02:10]\n"
        )
        agent = VisualScreenshotAgent(".", "/static/screenshots")

        plans = agent.plan_visual_screenshots(markdown, 900)

        self.assertGreaterEqual(len(plans), 2)
        self.assertTrue(any(plan.start <= 30 for plan in plans))
        self.assertTrue(any(110 <= plan.start <= 150 for plan in plans))
        self.assertTrue(all(plan.start < 850 for plan in plans))

    def test_filter_keeps_explicit_screenshot_markers_when_no_plan_exists(self):
        from app.services.visual_screenshot_agent import VisualScreenshotAgent

        markdown = (
            "## Dense demo *Content-[00:00]\n"
            "Important UI sequence.\n"
            "*Screenshot-[00:10]\n"
            "*Screenshot-[00:20]\n"
        )
        matches = VisualScreenshotAgent.extract_screenshot_timestamps(markdown)

        filtered_markdown, filtered = VisualScreenshotAgent.filter_screenshot_matches_by_structure(
            markdown,
            matches,
            [],
        )

        self.assertEqual(filtered, matches)
        self.assertIn("*Screenshot-[00:10]", filtered_markdown)
        self.assertIn("*Screenshot-[00:20]", filtered_markdown)

    def test_dense_short_section_keeps_multiple_visual_plans(self):
        from app.services.visual_screenshot_agent import VisualScreenshotAgent

        agent = VisualScreenshotAgent(".", "/static/screenshots")
        markdown = (
            "## UI 操作演示 *Content-[00:00]\n"
            "这里连续展示页面、参数、代码和最终结果。\n"
            "*Screenshot-[00:10]\n"
            "*Screenshot-[00:25]\n"
            "*Screenshot-[00:40]\n"
            "*Screenshot-[00:55]\n"
        )

        plans = agent.plan_visual_screenshots(markdown, 90)

        self.assertGreaterEqual(len(plans), 3)
        self.assertTrue(any(8 <= plan.start <= 14 for plan in plans))
        self.assertTrue(any(22 <= plan.start <= 30 for plan in plans))

    def test_real_langgraph_path_cleans_candidate_files_when_scoring_fails(self):
        from app.services.visual_screenshot_agent import VisualScreenshotAgent, VisualScreenshotState

        class _Reader:
            def __init__(self, *_args, **_kwargs):
                pass

            @staticmethod
            def _calculate_file_md5(path):
                return pathlib.Path(path).name

            @staticmethod
            def _score_frame(_path):
                raise RuntimeError("score failed")

            @staticmethod
            def _is_same_visual_state(_left, _right):
                return False

        with tempfile.TemporaryDirectory() as tmp_dir:
            created = []

            def _generate(_video_path, _output_dir, _timestamp, index):
                path = pathlib.Path(tmp_dir) / f"candidate_{index}.jpg"
                path.write_bytes(b"image")
                created.append(path)
                return str(path)

            agent = VisualScreenshotAgent(
                image_output_dir=tmp_dir,
                image_base_url="/static/screenshots",
                video_reader_cls=_Reader,
                screenshot_func=_generate,
            )
            state = VisualScreenshotState(
                markdown=(
                    "## UI demo *Content-[00:00]\n"
                    "This screen demo shows a UI, code, page, and final result.\n"
                    "*Screenshot-[00:10]\n"
                ),
                video_path=pathlib.Path("video.mp4"),
                duration=60,
            )

            result = agent.run(state)

        self.assertTrue(created)
        self.assertTrue(all(not path.exists() for path in created))
        self.assertIs(result, state)
        self.assertNotIn("*Screenshot", state.markdown)
        self.assertIn("score failed", "\n".join(state.diagnostics or []))

    def test_real_langgraph_path_fails_when_no_candidate_file_is_generated(self):
        from app.services.visual_screenshot_agent import VisualScreenshotAgent, VisualScreenshotState

        class _Reader:
            def __init__(self, *_args, **_kwargs):
                pass

            @staticmethod
            def _calculate_file_md5(path):
                return pathlib.Path(path).name

            @staticmethod
            def _score_frame(_path):
                return 0.92, 123

            @staticmethod
            def _is_same_visual_state(_left, _right):
                return False

        with tempfile.TemporaryDirectory() as tmp_dir:
            def _generate(_video_path, _output_dir, _timestamp, index):
                return str(pathlib.Path(tmp_dir) / f"missing_{index}.jpg")

            agent = VisualScreenshotAgent(
                image_output_dir=tmp_dir,
                image_base_url="/static/screenshots",
                video_reader_cls=_Reader,
                screenshot_func=_generate,
            )
            state = VisualScreenshotState(
                markdown=(
                    "## UI demo *Content-[00:00]\n"
                    "This screen demo shows a UI, code, page, and final result.\n"
                    "*Screenshot-[00:10]\n"
                ),
                video_path=pathlib.Path("video.mp4"),
                duration=60,
            )

            result = agent.run(state)

        self.assertIs(result, state)
        self.assertNotIn("*Screenshot", state.markdown)
        self.assertIn("未生成可用截图候选", "\n".join(state.diagnostics or []))

    def test_real_langgraph_path_fails_and_cleans_low_quality_candidate(self):
        from app.services.visual_screenshot_agent import VisualScreenshotAgent, VisualScreenshotState

        class _Reader:
            def __init__(self, *_args, **_kwargs):
                pass

            @staticmethod
            def _calculate_file_md5(path):
                return pathlib.Path(path).name

            @staticmethod
            def _score_frame(_path):
                return 0.1, 123

            @staticmethod
            def _is_same_visual_state(_left, _right):
                return False

        with tempfile.TemporaryDirectory() as tmp_dir:
            created = []

            def _generate(_video_path, _output_dir, _timestamp, index):
                path = pathlib.Path(tmp_dir) / f"low_quality_{index}.jpg"
                path.write_bytes(b"image")
                created.append(path)
                return str(path)

            agent = VisualScreenshotAgent(
                image_output_dir=tmp_dir,
                image_base_url="/static/screenshots",
                video_reader_cls=_Reader,
                screenshot_func=_generate,
            )
            state = VisualScreenshotState(
                markdown=(
                    "## UI demo *Content-[00:00]\n"
                    "This screen demo shows a UI, code, page, and final result.\n"
                    "*Screenshot-[00:10]\n"
                ),
                video_path=pathlib.Path("video.mp4"),
                duration=60,
            )

            result = agent.run(state)

        self.assertTrue(created)
        self.assertTrue(all(not path.exists() for path in created))
        self.assertIs(result, state)
        self.assertNotIn("*Screenshot", state.markdown)
        self.assertIn("截图候选质量过低", "\n".join(state.diagnostics or []))


if __name__ == "__main__":
    unittest.main()
