import os
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from app.downloaders.bilibili_downloader import BilibiliDownloader


class TestBilibiliVideoCacheQuality(unittest.TestCase):
    def test_download_video_does_not_reuse_low_resolution_cache(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = pathlib.Path(tmp_dir) / "BV1xx.mp4"
            video_path.write_bytes(b"low-resolution-cache")

            downloader = BilibiliDownloader.__new__(BilibiliDownloader)
            downloader._cookiefile = None
            calls = []

            def fake_extract_info(_url, download):
                calls.append(download)
                video_path.write_bytes(b"fresh-video")
                return {"id": "BV1xx"}

            with (
                patch("app.downloaders.bilibili_downloader.extract_video_id", return_value="BV1xx"),
                patch(
                    "app.downloaders.bilibili_downloader.is_screenshot_ready_video",
                    side_effect=[False, True],
                ),
                patch("app.downloaders.bilibili_downloader.yt_dlp.YoutubeDL") as youtube_dl,
            ):
                youtube_dl.return_value.__enter__.return_value.extract_info = fake_extract_info

                result = downloader.download_video("https://www.bilibili.com/video/BV1xx", tmp_dir)

            self.assertEqual(os.path.normpath(result), os.path.normpath(str(video_path)))
            self.assertEqual(video_path.read_bytes(), b"fresh-video")
            self.assertEqual(calls, [True])
            self.assertFalse(list(pathlib.Path(tmp_dir).glob("BV1xx.mp4.lowres.*")))

    def test_download_video_restores_low_resolution_cache_when_refresh_fails(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = pathlib.Path(tmp_dir) / "BV1xx.mp4"
            video_path.write_bytes(b"low-resolution-cache")

            downloader = BilibiliDownloader.__new__(BilibiliDownloader)
            downloader._cookiefile = None

            with (
                patch("app.downloaders.bilibili_downloader.extract_video_id", return_value="BV1xx"),
                patch("app.downloaders.bilibili_downloader.is_screenshot_ready_video", return_value=False),
                patch.object(BilibiliDownloader, "_download_video_via_api", side_effect=RuntimeError("api failed")),
                patch("app.downloaders.bilibili_downloader.yt_dlp.YoutubeDL") as youtube_dl,
            ):
                youtube_dl.return_value.__enter__.return_value.extract_info.side_effect = RuntimeError("yt failed")

                with self.assertRaisesRegex(RuntimeError, "api failed"):
                    downloader.download_video("https://www.bilibili.com/video/BV1xx", tmp_dir)

            self.assertEqual(video_path.read_bytes(), b"low-resolution-cache")
            self.assertFalse(list(pathlib.Path(tmp_dir).glob("BV1xx.mp4.lowres.*")))

    def test_download_video_rejects_new_low_resolution_video(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = pathlib.Path(tmp_dir) / "BV1xx.mp4"

            downloader = BilibiliDownloader.__new__(BilibiliDownloader)
            downloader._cookiefile = None

            def fake_extract_info(_url, download):
                self.assertTrue(download)
                video_path.write_bytes(b"new-low-resolution-video")
                return {"id": "BV1xx"}

            with (
                patch("app.downloaders.bilibili_downloader.extract_video_id", return_value="BV1xx"),
                patch("app.downloaders.bilibili_downloader.is_screenshot_ready_video", return_value=False),
                patch("app.downloaders.bilibili_downloader.yt_dlp.YoutubeDL") as youtube_dl,
            ):
                youtube_dl.return_value.__enter__.return_value.extract_info = fake_extract_info

                with self.assertRaisesRegex(RuntimeError, "清晰度不足"):
                    downloader.download_video("https://www.bilibili.com/video/BV1xx", tmp_dir)


if __name__ == "__main__":
    unittest.main()
