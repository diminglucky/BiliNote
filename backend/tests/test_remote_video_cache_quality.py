import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from app.downloaders.youtube_downloader import YoutubeDownloader


class TestRemoteVideoCacheQuality(unittest.TestCase):
    def test_youtube_download_video_refreshes_low_resolution_cache(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = pathlib.Path(tmp_dir) / "yt-1.mp4"
            video_path.write_bytes(b"low-resolution-cache")
            downloader = YoutubeDownloader.__new__(YoutubeDownloader)

            def fake_extract_info(_url, download):
                self.assertTrue(download)
                video_path.write_bytes(b"fresh-video")
                return {"id": "yt-1"}

            with (
                patch("app.downloaders.youtube_downloader.extract_video_id", return_value="yt-1"),
                patch(
                    "app.downloaders.youtube_downloader.is_screenshot_ready_video",
                    side_effect=[False, True],
                ),
                patch("app.downloaders.youtube_downloader.yt_dlp.YoutubeDL") as youtube_dl,
            ):
                youtube_dl.return_value.__enter__.return_value.extract_info = fake_extract_info

                result = downloader.download_video("https://youtube.com/watch?v=yt-1", tmp_dir)

            self.assertEqual(pathlib.Path(result), video_path)
            self.assertEqual(video_path.read_bytes(), b"fresh-video")
            self.assertFalse(list(pathlib.Path(tmp_dir).glob("yt-1.mp4.lowres.*")))


if __name__ == "__main__":
    unittest.main()
