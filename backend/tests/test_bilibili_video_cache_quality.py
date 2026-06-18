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
            ydl_opts = youtube_dl.call_args.args[0]
            self.assertIn("width>=1920", ydl_opts["format"])
            self.assertIn("bestvideo", ydl_opts["format"])
            self.assertFalse(list(pathlib.Path(tmp_dir).glob("BV1xx.mp4.lowres.*")))

    def test_bilibili_api_fallback_requests_1080p_dash_streams(self):
        downloader = BilibiliDownloader.__new__(BilibiliDownloader)

        with patch.object(BilibiliDownloader, "_api_get", return_value={}) as api_get:
            downloader._play_info_via_api({"id": "BV1xx", "cid": 123})

        params = api_get.call_args.args[1]
        self.assertEqual(params["qn"], 80)
        self.assertEqual(params["fnval"], 16)
        self.assertEqual(params["fourk"], 1)
        self.assertEqual(params["high_quality"], 1)

    def test_bilibili_api_fallback_downloads_best_1080p_candidate(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            downloader = BilibiliDownloader.__new__(BilibiliDownloader)
            selected_items = []

            def fake_extract_info(_url):
                return {"id": "BV1xx", "cid": 123}

            def fake_play_info(_info):
                return {
                    "dash": {
                        "video": [
                            {
                                "width": 852,
                                "height": 480,
                                "bandwidth": 3000,
                                "baseUrl": "https://example.com/480p.m4s",
                            },
                            {
                                "width": 1920,
                                "height": 1080,
                                "bandwidth": 1000,
                                "baseUrl": "https://example.com/1080p.m4s",
                            }
                        ]
                    }
                }

            def fake_download_stream(items, output_path):
                selected_items.extend(items)
                pathlib.Path(output_path).write_bytes(b"video-stream")

            def fake_run_ffmpeg(args):
                pathlib.Path(args[-1]).write_bytes(b"mp4")

            with (
                patch.object(BilibiliDownloader, "_extract_info_via_api", side_effect=fake_extract_info),
                patch.object(BilibiliDownloader, "_play_info_via_api", side_effect=fake_play_info),
                patch.object(BilibiliDownloader, "_download_stream", side_effect=fake_download_stream),
                patch.object(BilibiliDownloader, "_run_ffmpeg", side_effect=fake_run_ffmpeg),
            ):
                result = downloader._download_video_via_api(
                    "https://www.bilibili.com/video/BV1xx",
                    tmp_dir,
                )

            self.assertEqual(pathlib.Path(result), pathlib.Path(tmp_dir) / "BV1xx.mp4")
            self.assertEqual(selected_items[0]["width"], 1920)

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

    def test_download_video_continues_with_new_low_resolution_video(self):
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

                result = downloader.download_video("https://www.bilibili.com/video/BV1xx", tmp_dir)

            self.assertEqual(os.path.normpath(result), os.path.normpath(str(video_path)))
            self.assertEqual(video_path.read_bytes(), b"new-low-resolution-video")

    def test_download_video_replaces_low_resolution_yt_dlp_result_with_better_api_video(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            video_path = pathlib.Path(tmp_dir) / "BV1xx.mp4"
            video_path.write_bytes(b"low-resolution-cache")

            downloader = BilibiliDownloader.__new__(BilibiliDownloader)
            downloader._cookiefile = None

            def fake_extract_info(_url, download):
                self.assertTrue(download)
                video_path.write_bytes(b"yt-low-resolution")
                return {"id": "BV1xx"}

            api_video_path = pathlib.Path(tmp_dir) / "BV1xx.api.mp4"

            def fake_download_video_via_api(_url, _output_dir):
                api_video_path.write_bytes(b"api-high-resolution")
                return str(api_video_path)

            with (
                patch("app.downloaders.bilibili_downloader.extract_video_id", return_value="BV1xx"),
                patch(
                    "app.downloaders.bilibili_downloader.is_screenshot_ready_video",
                    side_effect=[False, False, False],
                ),
                patch(
                    "app.downloaders.bilibili_downloader.BilibiliDownloader._is_better_video",
                    return_value=True,
                ),
                patch.object(BilibiliDownloader, "_download_video_via_api", side_effect=fake_download_video_via_api),
                patch("app.downloaders.bilibili_downloader.yt_dlp.YoutubeDL") as youtube_dl,
            ):
                youtube_dl.return_value.__enter__.return_value.extract_info = fake_extract_info

                result = downloader.download_video("https://www.bilibili.com/video/BV1xx", tmp_dir)

            self.assertEqual(pathlib.Path(result), video_path)
            self.assertEqual(video_path.read_bytes(), b"api-high-resolution")

    def test_download_video_refreshes_cookie_before_download(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            downloader = BilibiliDownloader.__new__(BilibiliDownloader)
            downloader._cookie_mgr = type("_CookieMgr", (), {"get": lambda *_args: "SESSDATA=new"})()
            downloader._cookie = "SESSDATA=old"
            downloader._cookiefile = None

            with patch.object(BilibiliDownloader, "_write_netscape_cookie_file", return_value="cookie.tmp") as writer:
                downloader._refresh_cookie()

            self.assertEqual(downloader._cookie, "SESSDATA=new")
            self.assertEqual(downloader._cookiefile, "cookie.tmp")
            writer.assert_called_once()

    def test_download_video_refreshes_cookie_even_if_init_was_skipped(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            downloader = BilibiliDownloader.__new__(BilibiliDownloader)
            downloader._cookie = ""
            downloader._cookiefile = None

            with (
                patch("app.downloaders.bilibili_downloader.CookieConfigManager") as mgr_cls,
                patch.object(BilibiliDownloader, "_write_netscape_cookie_file", return_value="cookie.tmp"),
            ):
                mgr_cls.return_value.get.return_value = "SESSDATA=new"
                downloader._refresh_cookie()

            self.assertEqual(downloader._cookie, "SESSDATA=new")
            self.assertEqual(downloader._cookiefile, "cookie.tmp")


if __name__ == "__main__":
    unittest.main()
