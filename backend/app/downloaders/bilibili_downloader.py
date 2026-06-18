import os
import json
import logging
import subprocess
import tempfile
from abc import ABC
from typing import Union, Optional, List

import requests
import yt_dlp

from app.downloaders.base import Downloader, DownloadQuality, QUALITY_MAP
from app.downloaders.bilibili_subtitle import BilibiliSubtitleFetcher
from app.models.notes_model import AudioDownloadResult
from app.models.transcriber_model import TranscriptResult, TranscriptSegment
from app.utils.path_helper import get_data_dir
from app.utils.url_parser import extract_video_id
from app.services.cookie_manager import CookieConfigManager
from app.utils.video_quality import (
    cleanup_quarantined_video,
    is_screenshot_ready_video,
    probe_video_size,
    quarantine_low_quality_video,
    restore_quarantined_video,
    screenshot_quality_failure_message,
    screenshot_video_format_selector,
)

logger = logging.getLogger(__name__)

BILIBILI_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
class BilibiliDownloader(Downloader, ABC):
    def __init__(self):
        super().__init__()
        self._cookie_mgr = CookieConfigManager()
        self._cookie = ""
        self._cookiefile = None

    def _refresh_cookie(self) -> None:
        cookie_mgr = getattr(self, "_cookie_mgr", None)
        if cookie_mgr is None:
            cookie_mgr = CookieConfigManager()
            self._cookie_mgr = cookie_mgr

        current_cookie = cookie_mgr.get('bilibili') or ""
        current_cookie = current_cookie.strip()
        if current_cookie == getattr(self, "_cookie", "") and getattr(self, "_cookiefile", None) and os.path.exists(self._cookiefile):
            return
        self._cookie = current_cookie
        if getattr(self, "_cookiefile", None) and os.path.exists(self._cookiefile):
            try:
                os.remove(self._cookiefile)
            except Exception:
                pass
        self._cookiefile = self._write_netscape_cookie_file() if self._cookie else None

    def _write_netscape_cookie_file(self) -> Optional[str]:
        """Write Bilibili cookies to a Netscape-format file for yt-dlp."""
        if not self._cookie:
            logger.warning("Bilibili cookie is not configured; download may fail")
            return None
        lines = ["# Netscape HTTP Cookie File\n"]
        for pair in self._cookie.split("; "):
            if "=" in pair:
                key, value = pair.split("=", 1)
                lines.append(f".bilibili.com\tTRUE\t/\tFALSE\t0\t{key}\t{value}\n")
        tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False, encoding='utf-8')
        tmp.writelines(lines)
        tmp.close()
        logger.info("Generated Bilibili Netscape cookie file: %s (entries: %d)", tmp.name, len(lines) - 1)
        return tmp.name

    def download(
        self,
        video_url: str,
        output_dir: Union[str, None] = None,
        quality: DownloadQuality = "fast",
        need_video: Optional[bool] = False,
        skip_download: bool = False,
    ) -> AudioDownloadResult:
        self._refresh_cookie()
        if output_dir is None:
            output_dir = get_data_dir()
        if not output_dir:
            output_dir=self.cache_data
        os.makedirs(output_dir, exist_ok=True)

        video_id = extract_video_id(video_url, "bilibili")
        cached_audio_path = os.path.join(output_dir, f"{video_id}.mp3") if video_id else None
        if cached_audio_path and os.path.exists(cached_audio_path):
            info = self._cached_info(video_id) or self._minimal_info(video_id)
            return self._build_audio_result(info, cached_audio_path)

        if skip_download:
            info = self._extract_info(video_url)
            audio_path = cached_audio_path or os.path.join(output_dir, f"{info.get('id')}.mp3")
            return self._build_audio_result(info, audio_path)

        output_path = os.path.join(output_dir, "%(id)s.%(ext)s")

        ydl_opts = {
            'format': 'bestaudio[ext=m4a]/bestaudio/best',
            'outtmpl': output_path,
            'http_headers': {'Referer': 'https://www.bilibili.com'},
            'postprocessors': [
                {
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '64',
                }
            ],
            'noplaylist': True,
            'quiet': False,
        }
        if self._cookiefile:
            ydl_opts['cookiefile'] = self._cookiefile

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=True)
        except Exception:
            if cached_audio_path and os.path.exists(cached_audio_path):
                info = self._cached_info(video_id) or self._minimal_info(video_id)
                return self._build_audio_result(info, cached_audio_path)
            logger.warning("yt-dlp failed to download Bilibili audio; falling back to Bilibili API", exc_info=True)
            return self._download_audio_via_api(video_url, output_dir, quality)

        audio_path = os.path.join(output_dir, f"{info.get('id')}.mp3")
        return self._build_audio_result(info, audio_path)

    def _extract_info(self, video_url: str) -> dict:
        self._refresh_cookie()
        ydl_opts = {
            'skip_download': True,
            'quiet': True,
            'http_headers': {'Referer': 'https://www.bilibili.com'},
            'noplaylist': True,
        }
        if self._cookiefile:
            ydl_opts['cookiefile'] = self._cookiefile
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(video_url, download=False)
        except Exception:
            logger.warning("yt-dlp failed to extract Bilibili metadata; falling back to Bilibili API", exc_info=True)
            return self._extract_info_via_api(video_url)

    def _headers(self) -> dict:
        headers = {
            "User-Agent": BILIBILI_UA,
            "Referer": "https://www.bilibili.com",
            "Origin": "https://www.bilibili.com",
            "Accept": "*/*",
        }
        if self._cookie:
            headers["Cookie"] = self._cookie
        return headers

    def _api_get(self, url: str, params: dict) -> dict:
        resp = requests.get(url, params=params, headers=self._headers(), timeout=20)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"Bilibili API error: code={data.get('code')}, message={data.get('message')}")
        return data.get("data") or {}

    def _extract_info_via_api(self, video_url: str) -> dict:
        bvid = extract_video_id(video_url, "bilibili")
        if not bvid:
            raise RuntimeError("Unable to extract BV id from Bilibili URL")

        data = self._api_get(
            "https://api.bilibili.com/x/web-interface/view",
            {"bvid": bvid},
        )
        return {
            "id": data.get("bvid") or bvid,
            "title": data.get("title") or bvid,
            "duration": data.get("duration") or 0,
            "thumbnail": data.get("pic"),
            "tags": [item for item in [data.get("tname"), data.get("tname_v2")] if item],
            "cid": data.get("cid"),
            "raw_api_info": data,
        }

    def _play_info_via_api(self, info: dict) -> dict:
        bvid = info.get("id")
        cid = info.get("cid")
        if not bvid or not cid:
            raise RuntimeError("Bilibili play info missing bvid/cid")
        return self._api_get(
            "https://api.bilibili.com/x/player/playurl",
            {
                "bvid": bvid,
                "cid": cid,
                "qn": 80,
                "fnval": 16,
                "fourk": 1,
                "high_quality": 1,
            },
        )

    @staticmethod
    def _stream_candidates(item: dict) -> List[str]:
        urls = []
        for key in ("baseUrl", "base_url"):
            if item.get(key):
                urls.append(item[key])
        for key in ("backupUrl", "backup_url"):
            backup = item.get(key) or []
            urls.extend(backup)
        return urls

    def _download_stream(self, items: List[dict], output_path: str) -> None:
        errors = []
        for item in items:
            for url in self._stream_candidates(item):
                try:
                    with requests.get(url, headers=self._headers(), stream=True, timeout=(10, 120)) as resp:
                        resp.raise_for_status()
                        with open(output_path, "wb") as f:
                            for chunk in resp.iter_content(chunk_size=1024 * 1024):
                                if chunk:
                                    f.write(chunk)
                    if os.path.getsize(output_path) > 0:
                        return
                except Exception as exc:
                    errors.append(str(exc))
                    if os.path.exists(output_path):
                        os.remove(output_path)
        raise RuntimeError("Bilibili stream download failed: " + "; ".join(errors[-3:]))

    @staticmethod
    def _run_ffmpeg(args: List[str]) -> None:
        result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            raise RuntimeError((result.stderr or result.stdout or "ffmpeg failed").strip()[-1000:])

    @staticmethod
    def _video_resolution_rank(video_path: str) -> tuple[int, int]:
        size = probe_video_size(video_path)
        if size is None:
            return (0, 0)
        return size

    @classmethod
    def _is_better_video(cls, candidate_path: str, current_path: str) -> bool:
        candidate_size = cls._video_resolution_rank(candidate_path)
        current_size = cls._video_resolution_rank(current_path)
        return candidate_size > current_size

    @staticmethod
    def _quality_bitrate(quality: DownloadQuality) -> str:
        key = getattr(quality, "value", quality)
        return QUALITY_MAP.get(key, "64")

    def _download_audio_via_api(
        self,
        video_url: str,
        output_dir: str,
        quality: DownloadQuality,
    ) -> AudioDownloadResult:
        info = self._extract_info_via_api(video_url)
        play_info = self._play_info_via_api(info)
        audios = (play_info.get("dash") or {}).get("audio") or []
        if not audios:
            raise RuntimeError("Bilibili API did not return an audio stream")

        audios = sorted(audios, key=lambda item: item.get("bandwidth") or 0, reverse=True)
        video_id = info.get("id")
        tmp_audio = os.path.join(output_dir, f"{video_id}.audio.m4s")
        audio_path = os.path.join(output_dir, f"{video_id}.mp3")
        self._download_stream(audios, tmp_audio)
        try:
            self._run_ffmpeg([
                "ffmpeg", "-y",
                "-i", tmp_audio,
                "-vn",
                "-acodec", "libmp3lame",
                "-b:a", f"{self._quality_bitrate(quality)}k",
                audio_path,
            ])
        finally:
            if os.path.exists(tmp_audio):
                os.remove(tmp_audio)
        return self._build_audio_result(info, audio_path)

    def _download_video_via_api(self, video_url: str, output_dir: str) -> str:
        info = self._extract_info_via_api(video_url)
        play_info = self._play_info_via_api(info)
        videos = (play_info.get("dash") or {}).get("video") or []
        if not videos:
            raise RuntimeError("Bilibili API did not return a video stream")

        # Screenshots need a stable, clear video stream. Prefer about 1080p to avoid huge 4K files when cookies allow them.
        videos = sorted(
            videos,
            key=lambda item: (
                1 if ((item.get("width") or 0) > 1920 or (item.get("height") or 0) > 1080) else 0,
                abs(min(item.get("width") or 0, 1920) - 1920),
                abs(min(item.get("height") or 0, 1080) - 1080),
                -(item.get("bandwidth") or 0),
            ),
        )
        video_id = info.get("id")
        return self._download_video_streams(videos, output_dir, video_id, suffix="")

    def _download_video_streams(self, videos: List[dict], output_dir: str, video_id: str, suffix: str = "") -> str:
        tmp_video = os.path.join(output_dir, f"{video_id}{suffix}.video.m4s")
        video_path = os.path.join(output_dir, f"{video_id}{suffix}.mp4")
        self._download_stream(videos, tmp_video)
        try:
            self._run_ffmpeg([
                "ffmpeg", "-y",
                "-i", tmp_video,
                "-c", "copy",
                video_path,
            ])
        finally:
            if os.path.exists(tmp_video):
                os.remove(tmp_video)
        return video_path

    def _cached_info(self, video_id: str) -> Optional[dict]:
        if not video_id:
            return None
        search_roots = [
            os.getcwd(),
            os.path.dirname(os.getcwd()),
        ]
        for root in search_roots:
            audio_cache = os.path.join(root, "note_results", f"{video_id}_audio.json")
            if not os.path.exists(audio_cache):
                continue
            try:
                with open(audio_cache, "r", encoding="utf-8") as f:
                    data = json.load(f)
                info = data.get("raw_info") or {}
                info.setdefault("id", data.get("video_id") or video_id)
                info.setdefault("title", data.get("title") or video_id)
                info.setdefault("duration", data.get("duration", 0))
                info.setdefault("thumbnail", data.get("cover_url"))
                return info
            except Exception:
                continue
        return None

    def _minimal_info(self, video_id: str) -> dict:
        return {
            "id": video_id,
            "title": video_id,
            "duration": 0,
            "thumbnail": None,
            "tags": [],
        }

    def _build_audio_result(self, info: dict, audio_path: str) -> AudioDownloadResult:
        video_id = info.get("id")
        return AudioDownloadResult(
            file_path=audio_path,
            title=info.get("title"),
            duration=info.get("duration", 0),
            cover_url=info.get("thumbnail"),
            platform="bilibili",
            video_id=video_id,
            raw_info=info,
            video_path=None
        )

    def download_video(
        self,
        video_url: str,
        output_dir: Union[str, None] = None,
    ) -> str:
        """
        Download video and return the local video file path.
        """
        self._refresh_cookie()
        if output_dir is None:
            output_dir = get_data_dir()
        os.makedirs(output_dir, exist_ok=True)
        video_id=extract_video_id(video_url, "bilibili")
        video_path = os.path.join(output_dir, f"{video_id}.mp4")
        if os.path.exists(video_path) and is_screenshot_ready_video(video_path):
            return video_path
        low_quality_cache_path = quarantine_low_quality_video(video_path)

        # Low-resolution caches are quarantined while we try to refresh a clearer source.
        # If refresh fails, the old cache is restored so note generation can continue.

        output_path = os.path.join(output_dir, "%(id)s.%(ext)s")

        ydl_opts = {
            'format': screenshot_video_format_selector(),
            'outtmpl': output_path,
            'http_headers': {'Referer': 'https://www.bilibili.com'},
            'noplaylist': True,
            'quiet': False,
            'merge_output_format': 'mp4',
        }
        if self._cookiefile:
            ydl_opts['cookiefile'] = self._cookiefile

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=True)
                video_id = info.get("id")
                video_path = os.path.join(output_dir, f"{video_id}.mp4")
        except Exception:
            logger.warning("yt-dlp failed to download Bilibili video; falling back to Bilibili API", exc_info=True)
            try:
                video_path = self._download_video_via_api(video_url, output_dir)
            except Exception:
                restore_quarantined_video(low_quality_cache_path, video_path)
                raise

        if not os.path.exists(video_path):
            restore_quarantined_video(low_quality_cache_path, video_path)
            raise FileNotFoundError(f"Video file not found: {video_path}")
        if not is_screenshot_ready_video(video_path):
            api_candidate_path = os.path.join(output_dir, f"{video_id}.api.mp4")
            try:
                api_video_path = self._download_video_via_api(video_url, output_dir)
                if self._is_better_video(api_video_path, video_path):
                    os.replace(api_video_path, video_path)
                    logger.info("Bilibili API returned a clearer video; replaced the yt-dlp result")
                elif api_video_path != video_path and os.path.exists(api_video_path):
                    os.remove(api_video_path)
            except Exception as exc:
                logger.warning("yt-dlp video is source-limited, and Bilibili API fallback also failed: %s", exc)
            if not is_screenshot_ready_video(video_path):
                logger.warning("%s; continuing with the current video.", screenshot_quality_failure_message(video_path))
        cleanup_quarantined_video(low_quality_cache_path)

        return video_path

    def delete_video(self, video_path: str) -> str:
        """
        删除视频文件
        """
        if os.path.exists(video_path):
            os.remove(video_path)
            return f"Video file deleted: {video_path}"
        else:
            return f"Video file not found: {video_path}"

    def download_subtitles(self, video_url: str, output_dir: str = None,
                           langs: List[str] = None) -> Optional[TranscriptResult]:
        """
        Try to fetch Bilibili subtitles.
        :param video_url: 视频链接
        :param output_dir: 输出路径
        :param langs: 优先语言列表
        :return: TranscriptResult or None
        """
        self._refresh_cookie()
        # 1) Prefer the official player API. AI subtitles require SESSDATA cookies.
        try:
            result = BilibiliSubtitleFetcher().fetch_subtitles(video_url)
            if result and result.segments:
                return result
        except Exception as e:
            logger.warning(f"player API subtitle fetch failed; falling back to yt-dlp: {e}")

        # 2) Fallback to yt-dlp, which can be more sensitive to signature/cookie issues.
        if output_dir is None:
            output_dir = get_data_dir()
        if not output_dir:
            output_dir = self.cache_data
        os.makedirs(output_dir, exist_ok=True)

        if langs is None:
            langs = ['zh-Hans', 'zh', 'zh-CN', 'ai-zh', 'en', 'en-US']

        video_id = extract_video_id(video_url, "bilibili")

        ydl_opts = {
            'writesubtitles': True,
            'writeautomaticsub': True,
            'subtitleslangs': langs,
            'subtitlesformat': 'srt/json3/best',  # 支持多种格式
            'skip_download': True,
            'outtmpl': os.path.join(output_dir, f'{video_id}.%(ext)s'),
            'quiet': True,
        }

        # Inject Bilibili cookies through CookieConfigManager as a Netscape cookie file.
        if self._cookiefile:
            ydl_opts['cookiefile'] = self._cookiefile
            ydl_opts['http_headers'] = {'Referer': 'https://www.bilibili.com'}

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=True)

                # Find downloaded subtitle metadata.
                subtitles = info.get('requested_subtitles') or {}
                if not subtitles:
                    logger.info("Bilibili video %s has no available subtitles", video_id)
                    return None

                # 按优先级查找字幕
                detected_lang = None
                sub_info = None
                for lang in langs:
                    if lang in subtitles:
                        detected_lang = lang
                        sub_info = subtitles[lang]
                        break

                # 如果按优先级没找到，取第一个可用的（排除弹幕）
                if not detected_lang:
                    for lang, info_item in subtitles.items():
                        if lang != 'danmaku':  # 排除弹幕
                            detected_lang = lang
                            sub_info = info_item
                            break

                if not sub_info:
                    logger.info("Bilibili video %s has no available subtitles after excluding danmaku", video_id)
                    return None

                # yt-dlp can sometimes return subtitle content directly in the metadata.
                if 'data' in sub_info and sub_info['data']:
                    logger.info("Parsing subtitle data returned directly for language %s", detected_lang)
                    return self._parse_srt_content(sub_info['data'], detected_lang)

                # 查找字幕文件
                ext = sub_info.get('ext', 'srt')
                subtitle_file = os.path.join(output_dir, f"{video_id}.{detected_lang}.{ext}")

                if not os.path.exists(subtitle_file):
                    logger.info("Subtitle file does not exist: %s", subtitle_file)
                    return None

                # 根据格式解析字幕文件
                if ext == 'json3':
                    return self._parse_json3_subtitle(subtitle_file, detected_lang)
                else:
                    with open(subtitle_file, 'r', encoding='utf-8') as f:
                        return self._parse_srt_content(f.read(), detected_lang)

        except Exception as e:
            logger.warning("Failed to fetch Bilibili subtitles: %s", e)
            return None

    def _parse_srt_content(self, srt_content: str, language: str) -> Optional[TranscriptResult]:
        """
        解析 SRT 格式字幕内容

        :param srt_content: SRT 字幕文本内容
        :param language: 语言代码
        :return: TranscriptResult
        """
        import re
        try:
            segments = []
            # SRT 格式: 序号\n时间戳\n文本\n\n
            pattern = r'(\d+)\n(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})\n(.*?)(?=\n\n|\n\d+\n|$)'
            matches = re.findall(pattern, srt_content, re.DOTALL)

            for match in matches:
                idx, start_time, end_time, text = match
                text = text.strip()
                if not text:
                    continue

                # Convert SRT time format 00:00:00,000 to seconds.
                def time_to_seconds(t):
                    parts = t.replace(',', '.').split(':')
                    return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])

                segments.append(TranscriptSegment(
                    start=time_to_seconds(start_time),
                    end=time_to_seconds(end_time),
                    text=text
                ))

            if not segments:
                return None

            full_text = ' '.join(seg.text for seg in segments)
            logger.info("Parsed Bilibili SRT subtitles: %d segments", len(segments))
            return TranscriptResult(
                language=language,
                full_text=full_text,
                segments=segments,
                raw={'source': 'bilibili_subtitle', 'format': 'srt'}
            )

        except Exception as e:
            logger.warning(f"解析SRT字幕失败: {e}")
            return None

    def _parse_json3_subtitle(self, subtitle_file: str, language: str) -> Optional[TranscriptResult]:
        """
        解析 json3 格式字幕文件

        :param subtitle_file: 字幕文件路径
        :param language: 语言代码
        :return: TranscriptResult
        """
        try:
            with open(subtitle_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            segments = []
            events = data.get('events', [])

            for event in events:
                # json3 格式中时间单位是毫秒
                start_ms = event.get('tStartMs', 0)
                duration_ms = event.get('dDurationMs', 0)

                # 提取文本
                segs = event.get('segs', [])
                text = ''.join(seg.get('utf8', '') for seg in segs).strip()

                if text:
                    segments.append(TranscriptSegment(
                        start=start_ms / 1000.0,
                        end=(start_ms + duration_ms) / 1000.0,
                        text=text
                    ))

            if not segments:
                return None

            full_text = ' '.join(seg.text for seg in segments)

            logger.info("Parsed Bilibili subtitles: %d segments", len(segments))
            return TranscriptResult(
                language=language,
                full_text=full_text,
                segments=segments,
                raw={'source': 'bilibili_subtitle', 'file': subtitle_file}
            )

        except Exception as e:
            logger.warning(f"解析字幕文件失败: {e}")
            return None
