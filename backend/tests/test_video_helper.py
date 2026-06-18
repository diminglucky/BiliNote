import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from app.utils.video_helper import generate_screenshot


class TestVideoHelper(unittest.TestCase):
    def test_generate_screenshot_defaults_to_png_for_text_clarity(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            with patch("app.utils.video_helper.subprocess.run") as run:
                run.return_value.returncode = 0

                result = generate_screenshot("video.mp4", tmp_dir, 12, 3)

            self.assertTrue(result.endswith(".png"))
            command = run.call_args.args[0]
            self.assertNotIn("-q:v", command)
            self.assertEqual(pathlib.Path(result).parent, pathlib.Path(tmp_dir))

    def test_generate_screenshot_can_use_high_quality_jpeg_when_configured(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            with (
                patch.dict("os.environ", {"SCREENSHOT_IMAGE_FORMAT": "jpg", "SCREENSHOT_JPEG_QUALITY": "1"}),
                patch("app.utils.video_helper.subprocess.run") as run,
            ):
                run.return_value.returncode = 0

                result = generate_screenshot("video.mp4", tmp_dir, 12, 3)

            self.assertTrue(result.endswith(".jpg"))
            command = run.call_args.args[0]
            self.assertIn("-q:v", command)
            self.assertIn("1", command)


if __name__ == "__main__":
    unittest.main()
