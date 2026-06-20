import importlib.util
import pathlib
import shutil
import sys
import types
import unittest
import uuid

from PIL import Image, ImageDraw, ImageFilter


ROOT = pathlib.Path(__file__).resolve().parents[1]
TEST_TMP_ROOT = ROOT / ".test_tmp"


class ProjectTempDir:
    def __init__(self, prefix="video_reader_"):
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


def _load_video_reader_module():
    app_mod = types.ModuleType("app")
    utils_pkg = types.ModuleType("app.utils")
    app_mod.__path__ = [str(ROOT / "app")]
    utils_pkg.__path__ = [str(ROOT / "app" / "utils")]
    sys.modules["app"] = app_mod
    sys.modules["app.utils"] = utils_pkg

    logger_mod = types.ModuleType("app.utils.logger")
    logger_mod.get_logger = lambda *_args, **_kwargs: type(
        "_Logger",
        (),
        {"info": lambda *_a, **_k: None, "warning": lambda *_a, **_k: None, "error": lambda *_a, **_k: None},
    )()
    path_helper_mod = types.ModuleType("app.utils.path_helper")
    path_helper_mod.get_app_dir = lambda name: name

    sys.modules["app.utils.logger"] = logger_mod
    sys.modules["app.utils.path_helper"] = path_helper_mod

    import ffmpeg  # noqa: WPS433

    module_path = ROOT / "app" / "utils" / "video_reader.py"
    spec = importlib.util.spec_from_file_location("app.utils.video_reader", module_path)
    if spec is None or spec.loader is None:
        raise ImportError("video_reader module spec not found")
    module = importlib.util.module_from_spec(spec)
    sys.modules["app.utils.video_reader"] = module
    spec.loader.exec_module(module)
    return module


video_reader_module = _load_video_reader_module()
VideoReader = video_reader_module.VideoReader


class TestVideoReaderQuality(unittest.TestCase):
    def test_score_frame_penalizes_blurry_text_frame(self):
        with ProjectTempDir() as tmp_dir:
            clear_path = pathlib.Path(tmp_dir) / "clear.jpg"
            blurry_path = pathlib.Path(tmp_dir) / "blurry.jpg"

            img = Image.new("RGB", (1280, 720), "white")
            draw = ImageDraw.Draw(img)
            for row in range(8):
                draw.text((80, 70 + row * 70), f"Final result code output line {row}", fill="black")
            img.save(clear_path, quality=95)
            img.filter(ImageFilter.GaussianBlur(radius=4)).save(blurry_path, quality=95)

            reader = VideoReader(video_path="dummy.mp4")
            clear_score, _ = reader._score_frame(str(clear_path))
            blurry_score, _ = reader._score_frame(str(blurry_path))

        self.assertGreater(clear_score, blurry_score)
        self.assertLess(blurry_score, 0.42)

    def test_same_visual_state_matches_quality_benchmark_threshold(self):
        left = video_reader_module.FrameCandidate(
            path="left.jpg",
            timestamp=10,
            score=0.8,
            exact_hash="left",
            perceptual_hash=0b0000,
        )
        right = video_reader_module.FrameCandidate(
            path="right.jpg",
            timestamp=20,
            score=0.8,
            exact_hash="right",
            perceptual_hash=0b0111,
        )
        reader = VideoReader(video_path="dummy.mp4")

        self.assertTrue(reader._is_same_visual_state(left, right))


if __name__ == "__main__":
    unittest.main()
