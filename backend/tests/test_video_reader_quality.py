import importlib.util
import pathlib
import sys
import tempfile
import types
import unittest

from PIL import Image, ImageDraw, ImageFilter


ROOT = pathlib.Path(__file__).resolve().parents[1]


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
        with tempfile.TemporaryDirectory() as tmp_dir:
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


if __name__ == "__main__":
    unittest.main()
