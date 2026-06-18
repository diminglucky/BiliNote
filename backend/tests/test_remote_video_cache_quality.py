import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


from app.downloaders.youtube_downloader import YoutubeDownloader
from app.downloaders.douyin_downloader import DouyinDownloader
from app.downloaders.kuaishou_downloader import KuaiShouDownloader


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
            ydl_opts = youtube_dl.call_args.args[0]
            self.assertIn("width>=1920", ydl_opts["format"])
            self.assertIn("bestvideo", ydl_opts["format"])
            self.assertFalse(list(pathlib.Path(tmp_dir).glob("yt-1.mp4.lowres.*")))

    def test_douyin_download_video_continues_with_low_resolution_download(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = pathlib.Path(tmp_dir) / "dy-1.mp4"
            downloader = DouyinDownloader.__new__(DouyinDownloader)
            downloader.cache_data = tmp_dir
            downloader.headers_config = {}

            video_data = {
                "aweme_detail": {
                    "aweme_id": "dy-1",
                    "video": {"download_addr": {"url_list": ["https://example.com/video.mp4"]}},
                }
            }

            response = type("Response", (), {"content": b"low-resolution-video"})()

            with (
                patch.object(DouyinDownloader, "extract_video_id", return_value="dy-1"),
                patch.object(DouyinDownloader, "fetch_video_info", return_value=video_data),
                patch("app.downloaders.douyin_downloader.requests.get", return_value=response),
                patch("app.downloaders.douyin_downloader.is_screenshot_ready_video", return_value=False),
            ):
                result = downloader.download_video("https://douyin.example/video", tmp_dir)

            self.assertEqual(pathlib.Path(result), video_path)
            self.assertTrue(video_path.exists())

    def test_kuaishou_download_video_continues_with_low_resolution_download(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = pathlib.Path(tmp_dir) / "ks-1.mp4"
            video_path.write_bytes(b"low-resolution-video")
            downloader = KuaiShouDownloader.__new__(KuaiShouDownloader)

            result = type("Result", (), {"video_path": str(video_path)})()

            def fake_download(_url, _output_dir):
                video_path.write_bytes(b"low-resolution-video")
                return result

            with (
                patch.object(KuaiShouDownloader, "download", side_effect=fake_download),
                patch("app.downloaders.kuaishou_downloader.is_screenshot_ready_video", return_value=False),
            ):
                result_path = downloader.download_video("https://kuaishou.example/video", tmp_dir)

            self.assertEqual(pathlib.Path(result_path), video_path)


if __name__ == "__main__":
    unittest.main()
