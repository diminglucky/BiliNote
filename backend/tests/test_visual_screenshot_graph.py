import importlib.util
import pathlib
import sys
import tempfile
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

            with self.assertRaisesRegex(RuntimeError, "score failed"):
                agent.run(state)

            failed_files = [path for path in created if "fail_" in path.name]
            published_files = [pathlib.Path(path) for path in state.published_image_paths or []]
            self.assertTrue(published)
            self.assertTrue(published_files)
            self.assertTrue(all(path.exists() for path in published_files))
            self.assertTrue(all(not path.exists() for path in failed_files))

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

            with self.assertRaisesRegex(RuntimeError, "score failed"):
                agent.run(state)

        self.assertTrue(created)
        self.assertTrue(all(not path.exists() for path in created))

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

            with self.assertRaisesRegex(RuntimeError, "未生成可用截图候选"):
                agent.run(state)

        self.assertIn("*Screenshot", state.markdown)

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

            with self.assertRaisesRegex(RuntimeError, "截图候选质量过低"):
                agent.run(state)

        self.assertTrue(created)
        self.assertTrue(all(not path.exists() for path in created))


if __name__ == "__main__":
    unittest.main()
