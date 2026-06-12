import json
import logging
import os
import re
import tempfile
import base64
import mimetypes
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional, Tuple, Union, Any

from fastapi import HTTPException
from pydantic import HttpUrl
from dotenv import load_dotenv

from app.downloaders.base import Downloader
from app.downloaders.bilibili_downloader import BilibiliDownloader
from app.downloaders.douyin_downloader import DouyinDownloader
from app.downloaders.local_downloader import LocalDownloader
from app.downloaders.youtube_downloader import YoutubeDownloader
from app.db.video_task_dao import delete_task_by_video, insert_video_task
from app.enmus.exception import NoteErrorEnum, ProviderErrorEnum
from app.enmus.task_status_enums import TaskStatus
from app.enmus.note_enums import DownloadQuality
from app.exceptions.note import NoteError
from app.exceptions.provider import ProviderError
from app.gpt.base import GPT
from app.gpt.gpt_factory import GPTFactory
from app.models.audio_model import AudioDownloadResult
from app.models.gpt_model import GPTSource
from app.models.model_config import ModelConfig
from app.models.notes_model import AudioDownloadResult, NoteResult
from app.models.transcriber_model import TranscriptResult, TranscriptSegment
from app.services.constant import SUPPORT_PLATFORM_MAP
from app.services.provider import ProviderService
from app.transcriber.base import Transcriber
from app.transcriber.transcriber_provider import get_transcriber, _transcribers
from app.utils.note_helper import replace_content_markers, prepend_source_link
from app.utils.screenshot_marker import extract_screenshot_timestamps
from app.utils.status_code import StatusCode
from app.utils.video_helper import generate_screenshot
from app.utils.video_reader import FrameCandidate, VideoReader

# ------------------ 环境变量与全局配置 ------------------

# 从 .env 文件中加载环境变量
load_dotenv()

# 后端 API 地址与端口（若有需要可以在代码其他部分使用 BACKEND_BASE_URL）
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost")
BACKEND_PORT = os.getenv("BACKEND_PORT", "8483")
BACKEND_BASE_URL = f"{API_BASE_URL}:{BACKEND_PORT}"

# 输出目录（用于缓存音频、转写、Markdown 文件，以及存储截图）
NOTE_OUTPUT_DIR = Path(os.getenv("NOTE_OUTPUT_DIR", "note_results"))
NOTE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
IMAGE_OUTPUT_DIR = os.getenv("OUT_DIR", "./static/screenshots")
# 图片基础 URL（用于生成 Markdown 中的图片链接，需前端静态目录对应）
IMAGE_BASE_URL = os.getenv("IMAGE_BASE_URL", "/static/screenshots")

# 日志配置
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


@dataclass
class VisualSectionPlan:
    title: str
    start: int
    end: int
    score: float
    reasons: List[str]
    line_index: int


class NoteGenerator:
    """
    NoteGenerator 用于执行视频/音频下载、转写、GPT 生成笔记、插入截图/链接、
    以及将任务信息写入状态文件与数据库等功能。
    """

    def __init__(self):
        from app.services.transcriber_config_manager import TranscriberConfigManager
        config_manager = TranscriberConfigManager()
        self.model_size: str = config_manager.get_whisper_model_size()
        self.device: Optional[str] = None
        self.transcriber_type: str = config_manager.get_transcriber_type()
        self.transcriber: Transcriber = self._init_transcriber()
        self.video_path: Optional[Path] = None
        self.video_img_urls=[]
        logger.info("NoteGenerator 初始化完成")


    # ---------------- 公有方法 ----------------

    def generate(
        self,
        video_url: Union[str, HttpUrl],
        platform: str,
        quality: DownloadQuality = DownloadQuality.medium,
        task_id: Optional[str] = None,
        model_name: Optional[str] = None,
        provider_id: Optional[str] = None,
        link: bool = False,
        screenshot: bool = False,
        _format: Optional[List[str]] = None,
        style: Optional[str] = None,
        extras: Optional[str] = None,
        output_path: Optional[str] = None,
        video_understanding: bool = False,
        video_interval: int = 0,
        grid_size: Optional[List[int]] = None,
    ) -> NoteResult | None:
        """
        主流程：按步骤依次下载、转写、GPT 总结、截图/链接处理、存库、返回 NoteResult。

        :param video_url: 视频或音频链接
        :param platform: 平台名称，对应 SUPPORT_PLATFORM_MAP 中的键
        :param quality: 下载音频的质量枚举
        :param task_id: 用于标识本次任务的唯一 ID，亦用于状态文件和缓存文件命名
        :param model_name: GPT 模型名称
        :param provider_id: 模型供应商 ID
        :param link: 是否在笔记中插入视频片段链接
        :param screenshot: 是否在笔记中替换 Screenshot 标记为图片
        :param _format: 包含 'link' 或 'screenshot' 等字符串的列表，决定后续处理
        :param style: GPT 生成笔记的风格
        :param extras: 额外参数，传递给 GPT
        :param output_path: 下载输出目录（可选）
        :param video_understanding: 是否需要视频拼图理解（生成缩略图）
        :param video_interval: 视频帧截取间隔（秒），仅在 video_understanding 为 True 时生效
        :param grid_size: 生成缩略图时的网格大小，如 [3, 3]
        :return: NoteResult 对象，包含 markdown 文本、转写结果和音频元信息
        """
        if grid_size is None:
            grid_size = []

        try:
            logger.info(f"开始生成笔记 (task_id={task_id})")
            self._update_status(task_id, TaskStatus.PARSING)

            # 获取下载器与 GPT 实例

            downloader = self._get_downloader(platform)
            gpt = self._get_gpt(model_name, provider_id)

            # 缓存文件路径
            audio_cache_file = NOTE_OUTPUT_DIR / f"{task_id}_audio.json"
            transcript_cache_file = NOTE_OUTPUT_DIR / f"{task_id}_transcript.json"
            markdown_cache_file = NOTE_OUTPUT_DIR / f"{task_id}_markdown.md"
            # 1. 获取字幕/转写：优先缓存 → 平台字幕 → 音频转写
            transcript = None

            # 尝试读取缓存
            if transcript_cache_file.exists():
                logger.info(f"检测到转写缓存 ({transcript_cache_file})，尝试读取")
                try:
                    data = json.loads(transcript_cache_file.read_text(encoding="utf-8"))
                    segments = [TranscriptSegment(**seg) for seg in data.get("segments", [])]
                    transcript = TranscriptResult(
                        language=data.get("language"),
                        full_text=data["full_text"],
                        segments=segments,
                    )
                    logger.info(f"已从缓存加载转写结果，共 {len(segments)} 段")
                except Exception as e:
                    logger.warning(f"加载转写缓存失败: {e}")

            # 缓存没有，尝试获取平台字幕
            if transcript is None:
                logger.info("尝试获取平台字幕（优先于音频下载）...")
                try:
                    transcript = downloader.download_subtitles(video_url)
                    if transcript and transcript.segments:
                        logger.info(f"成功获取平台字幕，共 {len(transcript.segments)} 段")
                        transcript_cache_file.write_text(
                            json.dumps(asdict(transcript), ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
                    else:
                        transcript = None
                        logger.info("平台无可用字幕，将下载音频后转写")
                except Exception as e:
                    logger.warning(f"获取平台字幕失败: {e}，将下载音频后转写")
                    transcript = None

            # 2. 下载音频/视频
            # 有字幕时只提取元信息，不下载音视频文件（除非需要截图/视频理解）
            has_transcript = transcript is not None
            need_full_download = not has_transcript or screenshot or video_understanding
            audio_meta = self._download_media(
                downloader=downloader,
                video_url=video_url,
                quality=quality,
                audio_cache_file=audio_cache_file,
                status_phase=TaskStatus.DOWNLOADING,
                platform=platform,
                output_path=output_path,
                screenshot=screenshot,
                video_understanding=video_understanding,
                video_interval=video_interval,
                grid_size=grid_size,
                skip_download=not need_full_download,
            )

            # 3. 如果前面没拿到字幕，走转写流程
            if transcript is None:
                transcript = self._get_transcript(
                    downloader=downloader,
                    video_url=video_url,
                    audio_file=audio_meta.file_path,
                    transcript_cache_file=transcript_cache_file,
                    status_phase=TaskStatus.TRANSCRIBING,
                    task_id=task_id,
                )

            # 3. GPT 总结
            gpt_supports_vision = getattr(gpt, "supports_vision", False)
            if video_understanding and self.video_img_urls and not gpt_supports_vision:
                logger.warning("当前模型不支持视觉输入，视频理解截图将不会发送给模型")

            markdown = self._summarize_text(
                audio_meta=audio_meta,
                transcript=transcript,
                gpt=gpt,
                markdown_cache_file=markdown_cache_file,
                link=link,
                screenshot=screenshot,
                formats=_format or [],
                style=style,
                extras=extras,
                video_img_urls=self.video_img_urls,
            )

            # 4. 截图 & 链接替换
            if _format:
                markdown = self._post_process_markdown(
                    markdown=markdown,
                    video_path=self.video_path,
                    formats=_format,
                    audio_meta=audio_meta,
                    platform=platform,
                    gpt=gpt,
                )

            markdown = prepend_source_link(markdown, str(video_url))

            # 5. 保存记录到数据库
            self._update_status(task_id, TaskStatus.SAVING)
            self._save_metadata(video_id=audio_meta.video_id, platform=platform, task_id=task_id)

            # 6. 完成
            self._update_status(task_id, TaskStatus.SUCCESS)
            logger.info(f"笔记生成成功 (task_id={task_id})")
            return NoteResult(markdown=markdown, transcript=transcript, audio_meta=audio_meta)

        except Exception as exc:
            logger.error(f"生成笔记流程异常 (task_id={task_id})：{exc}", exc_info=True)
            self._update_status(task_id, TaskStatus.FAILED, message=str(exc))
            return None

    @staticmethod
    def delete_note(video_id: str, platform: str) -> int:
        """
        删除数据库中对应 video_id 与 platform 的任务记录

        :param video_id: 视频 ID
        :param platform: 平台标识
        :return: 删除的记录数
        """
        logger.info(f"删除笔记记录 (video_id={video_id}, platform={platform})")
        return delete_task_by_video(video_id, platform)

    # ---------------- 私有方法 ----------------

    def _init_transcriber(self) -> Transcriber:
        """
        根据环境变量 TRANSCRIBER_TYPE 动态获取并实例化转写器
        """
        if self.transcriber_type not in _transcribers:
            logger.error(f"未找到支持的转写器：{self.transcriber_type}")
            raise Exception(f"不支持的转写器：{self.transcriber_type}")

        logger.info(f"使用转写器：{self.transcriber_type}")
        return get_transcriber(
            transcriber_type=self.transcriber_type,
            model_size=self.model_size,
        )

    def _get_gpt(self, model_name: Optional[str], provider_id: Optional[str]) -> GPT:
        """
        根据 provider_id 获取对应的 GPT 实例
        :param model_name: GPT 模型名称
        :param provider_id: 供应商 ID
        :return: GPT 实例
        """
        provider = ProviderService.get_provider_by_id(provider_id)
        if not provider:
            logger.error(f"[get_gpt] 未找到模型供应商: provider_id={provider_id}")
            raise ProviderError(code=ProviderErrorEnum.NOT_FOUND,message=ProviderErrorEnum.NOT_FOUND.message)
        logger.info(f"创建 GPT 实例 {provider_id}")
        config = ModelConfig(
            api_key=provider["api_key"],
            base_url=provider["base_url"],
            model_name=model_name,
            provider=provider["type"],
            name=provider["name"],
        )
        return GPTFactory().from_config(config)

    def _get_downloader(self, platform: str) -> Downloader:
        """
        根据平台名称获取对应的下载器实例

        :param platform: 平台标识，需在 SUPPORT_PLATFORM_MAP 中
        :return: 对应的 Downloader 子类实例
        """
        downloader_cls = SUPPORT_PLATFORM_MAP.get(platform)
        logger.debug(f"实例化下载器 -  {platform}")
        instance = None
        if not downloader_cls:
            logger.error(f"不支持的平台：{platform}")
            raise NoteError(code=NoteErrorEnum.PLATFORM_NOT_SUPPORTED.code,
                            message=NoteErrorEnum.PLATFORM_NOT_SUPPORTED.message)
        try:
            instance = downloader_cls
        except Exception as e:
            logger.error(f"实例化下载器失败：{e}")


        logger.info(f"使用下载器：{downloader_cls.__class__}")
        return instance

    def _update_status(self, task_id: Optional[str], status: Union[str, TaskStatus], message: Optional[str] = None):
        """
        创建或更新 {task_id}.status.json，记录当前任务状态

        :param task_id: 任务唯一 ID
        :param status: TaskStatus 枚举或自定义状态字符串
        :param message: 可选消息，用于记录失败原因等
        """
        if not task_id:
            return

        NOTE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        status_file = NOTE_OUTPUT_DIR / f"{task_id}.status.json"
        print(f"写入状态文件: {status_file} 当前状态: {status}")
        data = {"status": status.value if isinstance(status, TaskStatus) else status}
        if message:
            data["message"] = message

        try:
            # First create a temporary file
            temp_handle = tempfile.NamedTemporaryFile(
                mode='w',
                encoding='utf-8',
                delete=False,
                dir=str(NOTE_OUTPUT_DIR),
                prefix=f"{status_file.name}.",
                suffix='.tmp',
            )
            temp_file = Path(temp_handle.name)

            # Write to temporary file
            with temp_handle as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())

            # Atomic rename operation
            temp_file.replace(status_file)

            print(f"状态文件写入成功: {status_file}")
        except Exception as e:
            logger.error(f"写入状态文件失败 (task_id={task_id})：{e}")
            # Try to write error to file directly as fallback
            try:
                with status_file.open('w', encoding='utf-8') as f:
                    f.write(f"Error writing status: {str(e)}")
            except:
                logger.error(f"写入错误  {e}")

    def _handle_exception(self, task_id, exc):
        logger.error(f"任务异常 (task_id={task_id})", exc_info=True)
        error_message = getattr(exc, 'detail', str(exc))
        if isinstance(error_message, dict):
            try:
                error_message = json.dumps(error_message, ensure_ascii=False)
            except:
                error_message = str(error_message)
        self._update_status(task_id, TaskStatus.FAILED, message=error_message)

    def _download_media(
        self,
        downloader: Downloader,
        video_url: Union[str, HttpUrl],
        quality: DownloadQuality,
        audio_cache_file: Path,
        status_phase: TaskStatus,
        platform: str,
        output_path: Optional[str],
        screenshot: bool,
        video_understanding: bool,
        video_interval: int,
        grid_size: List[int],
        skip_download: bool = False,
    ) -> AudioDownloadResult | None:
        """
        1. 检查音频缓存；若不存在，则根据需要下载音频或视频（若需截图/可视化）。
        2. 如果需要视频，则先下载视频并生成缩略图集，再下载音频。
        3. 返回 AudioDownloadResult

        :param downloader: Downloader 实例
        :param video_url: 视频/音频链接
        :param quality: 音频下载质量
        :param audio_cache_file: 本地缓存 JSON 文件路径
        :param status_phase: 对应的状态枚举，如 TaskStatus.DOWNLOADING
        :param platform: 平台标识
        :param output_path: 下载输出目录（可为 None）
        :param screenshot: 是否需要在笔记中插入截图
        :param video_understanding: 是否需要生成缩略图
        :param video_interval: 视频截帧间隔
        :param grid_size: 缩略图网格尺寸
        :return: AudioDownloadResult 对象
        """
        task_id = audio_cache_file.stem.split("_")[0]
        self._update_status(task_id, status_phase)
        need_video = screenshot or video_understanding

        # 已有缓存，尝试加载
        if audio_cache_file.exists():
            logger.info(f"检测到音频缓存 ({audio_cache_file})，直接读取")
            try:
                data = json.loads(audio_cache_file.read_text(encoding="utf-8"))
                cached_audio = AudioDownloadResult(**data)
                cached_video_path = (cached_audio.video_path or "").strip() if cached_audio.video_path else ""

                # 需要视频（截图 / 视频理解）时，缓存里必须有可用 video_path；否则不能直接命中缓存。
                if need_video:
                    if cached_video_path and Path(cached_video_path).exists():
                        self.video_path = Path(cached_video_path)
                        return cached_audio
                    logger.info("缓存缺少可用 video_path，继续下载视频以支持截图/视频理解")
                else:
                    return cached_audio
            except Exception as e:
                logger.warning(f"读取音频缓存失败，将重新下载：{e}")

        # 有字幕且不需要截图/视频理解时，只提取元信息不下载文件
        if skip_download:
            logger.info("已有字幕，仅提取视频元信息（不下载音视频）")
            try:
                audio = downloader.download(
                    video_url=video_url,
                    quality=quality,
                    output_dir=output_path,
                    need_video=False,
                    skip_download=True,
                )
                audio_cache_file.write_text(
                    json.dumps(asdict(audio), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                logger.info(f"元信息提取完成 ({audio_cache_file})")
                return audio
            except Exception as exc:
                logger.warning(f"元信息提取失败，将尝试完整下载: {exc}")

        if need_video and not grid_size:
            grid_size = [2, 2]
        if grid_size:
            grid_size = [
                max(1, min(int(grid_size[0]), 4)),
                max(1, min(int(grid_size[1]), 4)),
            ]

        frame_interval = video_interval if video_interval and video_interval > 0 else 6
        if need_video:
            try:
                logger.info("开始下载视频")
                video_path_str = downloader.download_video(video_url)
                self.video_path = Path(video_path_str)
                logger.info(f"视频下载完成：{self.video_path}")

                if grid_size and os.getenv("BILINOTE_LEGACY_VIDEO_GRID", "").lower() in {"1", "true", "yes"}:
                    self.video_img_urls = VideoReader(
                        video_path=str(self.video_path),
                        grid_size=tuple(grid_size),
                        frame_interval=frame_interval,
                        unit_width=960,
                        unit_height=540,
                        save_quality=80,
                    ).run()
                else:
                    logger.info("未指定 grid_size，跳过缩略图生成")
            except Exception as exc:
                logger.error(f"视频下载失败：{exc}")
                self._handle_exception(task_id, exc)
                raise

        # 下载音频
        try:
            logger.info("开始下载音频")
            audio = downloader.download(
                video_url=video_url,
                quality=quality,
                output_dir=output_path,
                need_video=need_video,
            )
            audio_cache_file.write_text(json.dumps(asdict(audio), ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info(f"音频下载并缓存成功 ({audio_cache_file})")
            return audio
        except Exception as exc:
            logger.error(f"音频下载失败：{exc}")
            self._handle_exception(task_id, exc)
            raise


    def _get_transcript(
        self,
        downloader: Downloader,
        video_url: str,
        audio_file: str,
        transcript_cache_file: Path,
        status_phase: TaskStatus,
        task_id: Optional[str] = None,
    ) -> TranscriptResult | None:
        """
        优先获取平台字幕，没有则 fallback 到音频转写

        :param downloader: 下载器实例
        :param video_url: 视频链接
        :param audio_file: 音频文件路径（用于 fallback 转写）
        :param transcript_cache_file: 缓存文件路径
        :param status_phase: 状态枚举
        :param task_id: 任务 ID
        :return: TranscriptResult 对象
        """
        self._update_status(task_id, status_phase)

        # 已有缓存，直接返回
        if transcript_cache_file.exists():
            logger.info(f"检测到转写缓存 ({transcript_cache_file})，尝试读取")
            try:
                data = json.loads(transcript_cache_file.read_text(encoding="utf-8"))
                segments = [TranscriptSegment(**seg) for seg in data.get("segments", [])]
                return TranscriptResult(language=data.get("language"), full_text=data["full_text"], segments=segments)
            except Exception as e:
                logger.warning(f"加载转写缓存失败，将重新获取：{e}")

        # 1. 先尝试获取平台字幕
        logger.info("尝试获取平台字幕...")
        try:
            transcript = downloader.download_subtitles(video_url)
            if transcript and transcript.segments:
                logger.info(f"成功获取平台字幕，共 {len(transcript.segments)} 段")
                # 缓存结果
                transcript_cache_file.write_text(
                    json.dumps(asdict(transcript), ensure_ascii=False, indent=2),
                    encoding="utf-8"
                )
                return transcript
            else:
                logger.info("平台无可用字幕，将使用音频转写")
        except Exception as e:
            logger.warning(f"获取平台字幕失败: {e}，将使用音频转写")

        # 2. Fallback 到音频转写
        return self._transcribe_audio(
            audio_file=audio_file,
            transcript_cache_file=transcript_cache_file,
            status_phase=status_phase,
        )

    def _transcribe_audio(
        self,
        audio_file: str,
        transcript_cache_file: Path,
        status_phase: TaskStatus,
    ) -> TranscriptResult | None:
        """
        1. 检查转写缓存；若存在则尝试加载，否则调用转写器生成并缓存。
        2. 返回 TranscriptResult 对象

        :param audio_file: 音频文件本地路径
        :param transcript_cache_file: 转写结果缓存路径
        :param status_phase: 对应的状态枚举，如 TaskStatus.TRANSCRIBING
        :return: TranscriptResult 对象
        """
        task_id = transcript_cache_file.stem.split("_")[0]
        self._update_status(task_id, status_phase)

        # 已有缓存，尝试加载
        if transcript_cache_file.exists():
            logger.info(f"检测到转写缓存 ({transcript_cache_file})，尝试读取")
            try:
                data = json.loads(transcript_cache_file.read_text(encoding="utf-8"))
                segments = [TranscriptSegment(**seg) for seg in data.get("segments", [])]
                return TranscriptResult(language=data["language"], full_text=data["full_text"], segments=segments)
            except Exception as e:
                logger.warning(f"加载转写缓存失败，将重新转写：{e}")

        # 调用转写器
        try:
            logger.info("开始转写音频")
            transcript = self.transcriber.transcript(file_path=audio_file)
            transcript_cache_file.write_text(json.dumps(asdict(transcript), ensure_ascii=False, indent=2), encoding="utf-8")
            logger.info(f"转写并缓存成功 ({transcript_cache_file})")
            return transcript
        except Exception as exc:
            logger.error(f"音频转写失败：{exc}")
            self._handle_exception(task_id, exc)
            raise

    def _summarize_text(
        self,
        audio_meta: AudioDownloadResult,
        transcript: TranscriptResult,
        gpt: GPT,
        markdown_cache_file: Path,
        link: bool,
        screenshot: bool,
        formats: List[str],
        style: Optional[str],
        extras: Optional[str],
            video_img_urls: List[str],
    ) -> str | None:
        """
        调用 GPT 对转写结果进行总结，生成 Markdown 文本并缓存。

        :param audio_meta: AudioDownloadResult 元信息
        :param transcript: TranscriptResult 转写结果
        :param gpt: GPT 实例
        :param markdown_cache_file: Markdown 缓存路径
        :param link: 是否在笔记中插入链接
        :param screenshot: 是否在笔记中生成截图占位
        :param formats: 包含 'link' 或 'screenshot' 的列表
        :param style: GPT 输出风格
        :param extras: GPT 额外参数
        :return: 生成的 Markdown 字符串
        """
        task_id = markdown_cache_file.stem
        self._update_status(task_id, TaskStatus.SUMMARIZING)

        source = GPTSource(
            title=audio_meta.title,
            segment=transcript.segments,
            tags=audio_meta.raw_info.get("tags", []),
            screenshot=screenshot,
            video_img_urls=video_img_urls,
            link=link,
            _format=formats,
            style=style,
            extras=extras,
            checkpoint_key=task_id,
        )

        try:
            markdown = gpt.summarize(source)
            markdown_cache_file.write_text(markdown, encoding="utf-8")
            logger.info(f"GPT 总结并缓存成功 ({markdown_cache_file})")
            return markdown
        except Exception as exc:
            logger.error(f"GPT 总结失败：{exc}")
            self._handle_exception(task_id, exc)
            raise

    def _post_process_markdown(
        self,
        markdown: str,
        video_path: Optional[Path],
        formats: List[str],
        audio_meta: AudioDownloadResult,
        platform: str,
        gpt: Optional[GPT] = None,
    ) -> str:
        """
        对生成的 Markdown 做后期处理：插入截图和/或插入链接。

        :param markdown: 原始 Markdown 字符串
        :param video_path: 本地视频路径（可为 None）
        :param formats: 包含 'link' 或 'screenshot' 的列表
        :param audio_meta: AudioDownloadResult 元信息，用于链接替换
        :param platform: 平台标识，用于链接替换
        :return: 处理后的 Markdown 字符串
        """
        if "screenshot" in formats and video_path:
            try:
                updated = self._insert_screenshots(markdown, video_path, audio_meta.duration, gpt=gpt)
                if updated is not None:
                    markdown = updated
            except Exception as exc:
                logger.warning("截图插入失败，跳过该步骤")

        if "link" in formats:
            try:
                markdown = replace_content_markers(markdown, video_id=audio_meta.video_id, platform=platform)
            except Exception as e:
                logger.warning(f"链接插入失败，跳过该步骤：{e}")

        return markdown

    def _insert_screenshots(
        self,
        markdown: str,
        video_path: Path,
        duration: Optional[float] = None,
        gpt: Optional[GPT] = None,
    ) -> str | None | Any:
        """
        扫描 Markdown 文本中所有 Screenshot 标记，并替换为实际生成的截图链接。

        :param markdown: 含有 *Screenshot-mm:ss 或 Screenshot-[mm:ss] 标记的 Markdown 文本
        :param video_path: 本地视频文件路径
        :return: 替换后的 Markdown 字符串
        """
        matches: List[Tuple[str, int]] = extract_screenshot_timestamps(markdown)
        visual_plans = self._plan_visual_screenshots(markdown, duration)
        if matches:
            markdown, matches = self._filter_screenshot_matches_by_structure(markdown, matches, visual_plans)
        # 模型有时不会按约定输出 Screenshot 标记；此时兜底补几张关键帧，避免用户勾了截图却无图可见。
        if not matches:
            fallback_plans = visual_plans
            if not fallback_plans:
                return markdown
            fallback_images: List[Tuple[int, str]] = []
            visual_reader = VideoReader(
                video_path=str(video_path),
                frame_dir=str(IMAGE_OUTPUT_DIR),
                grid_dir=str(IMAGE_OUTPUT_DIR),
            )
            inserted_visuals: List[FrameCandidate] = []
            for idx, plan in enumerate(fallback_plans):
                ts = plan.start
                try:
                    candidate = self._best_screenshot_near_timestamp(
                        video_path=video_path,
                        timestamp=plan.start,
                        duration=duration,
                        index=idx,
                        visual_reader=visual_reader,
                        search_end=plan.end,
                        gpt=gpt,
                        section_title=plan.title,
                        section_context=self._section_context_for_plan(markdown, plan),
                    )
                    if candidate is None:
                        continue
                    if any(visual_reader._is_same_visual_state(prev, candidate) for prev in inserted_visuals):
                        Path(candidate.path).unlink(missing_ok=True)
                        continue
                    inserted_visuals.append(candidate)
                    img_path = candidate.path
                    filename = Path(img_path).name
                    img_url = f"{IMAGE_BASE_URL.rstrip('/')}/{filename}"
                    fallback_images.append((plan.start, f"![]({img_url})"))
                except Exception as exc:
                    logger.error(f"兜底截图失败 (timestamp={ts})：{exc}")
            if fallback_images:
                return self._insert_fallback_images_near_sections(markdown, fallback_images)
            return markdown

        visual_reader = VideoReader(
            video_path=str(video_path),
            frame_dir=str(IMAGE_OUTPUT_DIR),
            grid_dir=str(IMAGE_OUTPUT_DIR),
        )
        inserted_visuals: List[FrameCandidate] = []
        generated_images: List[Tuple[int, str]] = []
        for idx, (marker, ts) in enumerate(matches):
            try:
                plan = self._matching_visual_plan(ts, visual_plans)
                search_end = plan.end if plan else None
                candidate = self._best_screenshot_near_timestamp(
                    video_path=video_path,
                    timestamp=ts,
                    duration=duration,
                    index=idx,
                    visual_reader=visual_reader,
                    search_end=search_end,
                    gpt=gpt,
                    section_title=plan.title if plan else "",
                    section_context=self._section_context_for_plan(markdown, plan) if plan else "",
                )
                if candidate is None:
                    markdown = markdown.replace(marker, "", 1)
                    continue
                img_path = candidate.path
                if not Path(img_path).exists():
                    logger.error(f"生成截图失败 (timestamp={ts})：文件未生成")
                    continue
                if any(visual_reader._is_same_visual_state(prev, candidate) for prev in inserted_visuals):
                    Path(img_path).unlink(missing_ok=True)
                    markdown = markdown.replace(marker, "", 1)
                    continue
                inserted_visuals.append(candidate)
                filename = Path(img_path).name
                # 构建前端可访问的 URL，例如 /static/screenshots/{filename}
                img_url = f"{IMAGE_BASE_URL.rstrip('/')}/{filename}"
                markdown = markdown.replace(marker, f"![]({img_url})", 1)
                generated_images.append((candidate.timestamp, f"![]({img_url})"))
            except Exception as exc:
                logger.error(f"生成截图失败 (timestamp={ts})：{exc}")
                continue

        planned_times = {plan.start for plan in visual_plans}
        covered_times = {
            plan.start
            for image_ts, _image in generated_images
            for plan in visual_plans
            if max(0, plan.start - 45) <= image_ts <= plan.end + 15
        }
        missing_plans = [
            plan for plan in visual_plans
            if plan.start in planned_times and plan.start not in covered_times
        ]
        if missing_plans:
            fallback_images: List[Tuple[int, str]] = []
            start_index = len(matches)
            for offset, plan in enumerate(missing_plans):
                try:
                    candidate = self._best_screenshot_near_timestamp(
                        video_path=video_path,
                        timestamp=plan.start,
                        duration=duration,
                        index=start_index + offset,
                        visual_reader=visual_reader,
                        search_end=plan.end,
                        gpt=gpt,
                        section_title=plan.title,
                        section_context=self._section_context_for_plan(markdown, plan),
                    )
                    if candidate is None:
                        continue
                    if any(visual_reader._is_same_visual_state(prev, candidate) for prev in inserted_visuals):
                        Path(candidate.path).unlink(missing_ok=True)
                        continue
                    inserted_visuals.append(candidate)
                    filename = Path(candidate.path).name
                    img_url = f"{IMAGE_BASE_URL.rstrip('/')}/{filename}"
                    fallback_images.append((candidate.timestamp, f"![]({img_url})"))
                except Exception as exc:
                    logger.error(f"补充截图失败 (timestamp={plan.start})：{exc}")
            if fallback_images:
                markdown = self._insert_fallback_images_near_sections(markdown, fallback_images)
        return markdown

    @staticmethod
    def _matching_visual_plan(timestamp: int, plans: List[VisualSectionPlan]) -> Optional[VisualSectionPlan]:
        candidates = [
            plan for plan in plans
            if max(0, plan.start - 45) <= timestamp <= plan.end + 15
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda plan: abs(plan.start - timestamp))

    @staticmethod
    def _section_context_for_plan(markdown: str, plan: Optional[VisualSectionPlan]) -> str:
        if plan is None:
            return ""
        lines = markdown.splitlines()
        if plan.line_index >= len(lines):
            return plan.title
        end_line = NoteGenerator._next_heading_line(lines, plan.line_index)
        context = "\n".join(lines[plan.line_index:end_line]).strip()
        return context[:3000]

    @staticmethod
    def _image_data_url(path: str) -> str:
        mime_type = mimetypes.guess_type(path)[0] or "image/jpeg"
        with open(path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    @staticmethod
    def _extract_json_object(text: str) -> dict | None:
        text = (text or "").strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except Exception:
            pass
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except Exception:
            return None

    def _review_screenshot_candidates(
        self,
        candidates: List[FrameCandidate],
        gpt: Optional[GPT],
        section_title: str = "",
        section_context: str = "",
    ) -> Optional[FrameCandidate]:
        if not candidates or not gpt or not getattr(gpt, "supports_vision", False):
            return None
        client = getattr(gpt, "client", None)
        model = getattr(gpt, "model", None)
        if client is None or not model:
            return None

        max_candidates = min(8, len(candidates))
        if len(candidates) <= max_candidates:
            review_candidates = sorted(candidates, key=lambda item: item.timestamp)
        else:
            ordered = sorted(candidates, key=lambda item: item.timestamp)
            high_score = sorted(candidates, key=lambda item: item.score, reverse=True)[:4]
            spread = [
                ordered[round(idx * (len(ordered) - 1) / max(1, max_candidates - 1))]
                for idx in range(max_candidates)
            ]
            by_path = {}
            for item in high_score:
                by_path[item.path] = item
            for item in spread:
                if len(by_path) >= max_candidates:
                    break
                by_path[item.path] = item
            review_candidates = sorted(by_path.values(), key=lambda item: item.timestamp)

        prompt = (
            "你是 BiliNote 的截图评审器。请从候选截图中选择最适合插入学习笔记的一张。\n"
            "选择标准按优先级排序：\n"
            "1. 与当前章节标题和正文最相关。\n"
            "2. 信息完整，优先包含最终结果、更新后的计划、运行结果、完整流程图或关键代码。\n"
            "3. 避免空白页、过渡动画、刚开始出现的半成品画面、重复画面、无关字幕特写。\n"
            "4. 如果后面的截图只是更空或已经切到无关内容，不要为了靠后而选择它。\n"
            "只返回 JSON，不要输出解释文字。格式："
            "{\"selected\":候选序号整数,\"reason\":\"简短中文原因\",\"confidence\":0到1}\n\n"
            f"章节标题：{section_title or '未知'}\n"
            f"章节正文摘要：\n{section_context or '无'}\n\n"
            "候选截图如下："
        )
        content: list[dict] = [{"type": "text", "text": prompt}]
        for idx, candidate in enumerate(review_candidates):
            content.append({
                "type": "text",
                "text": (
                    f"候选 {idx}: 时间 {self._format_seconds(candidate.timestamp)}, "
                    f"启发式分数 {candidate.score:.3f}"
                ),
            })
            try:
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": self._image_data_url(candidate.path),
                        "detail": "high",
                    },
                })
            except Exception as exc:
                logger.warning(f"候选截图编码失败，跳过视觉评审: {exc}")
                return None

        try:
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": content}],
                    temperature=0,
                )
            except Exception as exc:
                raw = str(exc).lower()
                if "temperature" not in raw or (
                    "does not support" not in raw
                    and "unsupported_value" not in raw
                    and "only the default" not in raw
                ):
                    raise
                response = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": content}],
                )
        except Exception as exc:
            logger.warning(f"多模态截图评审失败，使用启发式结果: {exc}")
            return None

        raw = response.choices[0].message.content
        data = self._extract_json_object(raw)
        if not isinstance(data, dict):
            logger.warning(f"多模态截图评审返回非 JSON，使用启发式结果: {raw}")
            return None

        try:
            selected_idx = int(data.get("selected"))
        except Exception:
            return None
        confidence = data.get("confidence", 0)
        try:
            confidence_value = float(confidence)
        except Exception:
            confidence_value = 0
        if selected_idx < 0 or selected_idx >= len(review_candidates):
            return None
        if confidence_value < float(os.getenv("SCREENSHOT_REVIEW_MIN_CONFIDENCE", "0.35")):
            return None
        chosen = review_candidates[selected_idx]
        logger.info(
            "多模态截图评审选择: ts=%s score=%.3f reason=%s confidence=%.2f",
            chosen.timestamp,
            chosen.score,
            data.get("reason", ""),
            confidence_value,
        )
        return chosen

    @staticmethod
    def _format_seconds(seconds: int) -> str:
        seconds = max(0, int(seconds))
        hh = seconds // 3600
        mm = (seconds % 3600) // 60
        ss = seconds % 60
        if hh:
            return f"{hh:02d}:{mm:02d}:{ss:02d}"
        return f"{mm:02d}:{ss:02d}"

    @staticmethod
    def _content_line_markers(markdown: str) -> List[Tuple[int, int]]:
        pattern = r"(?:\*?)Content-(?:\[(\d{2}):(\d{2})\]|(\d{2}):(\d{2}))"
        heading_markers: List[Tuple[int, int]] = []
        fallback_markers: List[Tuple[int, int]] = []
        in_code_block = False
        for line_idx, line in enumerate(markdown.splitlines()):
            if line.strip().startswith("```"):
                in_code_block = not in_code_block
                continue
            if in_code_block:
                continue
            stripped = line.lstrip()
            is_heading = bool(re.match(r"^#{1,6}\s+", stripped))
            is_toc_link = bool(re.match(r"^[-*+]\s+\[", stripped))
            for match in re.finditer(pattern, line):
                mm = match.group(1) or match.group(3)
                ss = match.group(2) or match.group(4)
                marker = (line_idx, int(mm) * 60 + int(ss))
                if is_heading:
                    heading_markers.append(marker)
                elif not is_toc_link:
                    fallback_markers.append(marker)
        markers = heading_markers or fallback_markers
        return sorted(markers, key=lambda item: (item[1], item[0]))

    @staticmethod
    def _heading_line_markers_from_screenshots(markdown: str) -> List[Tuple[int, int]]:
        lines = markdown.splitlines()
        heading_lines = [
            idx for idx, line in enumerate(lines)
            if re.match(r"^#{1,6}\s+", line) and "目录" not in line and "AI总结" not in line
        ]
        markers: List[Tuple[int, int]] = []
        for pos, line_idx in enumerate(heading_lines):
            next_heading = heading_lines[pos + 1] if pos + 1 < len(heading_lines) else len(lines)
            section = "\n".join(lines[line_idx:next_heading])
            screenshot_matches = extract_screenshot_timestamps(section)
            if screenshot_matches:
                markers.append((line_idx, screenshot_matches[0][1]))
        return sorted(markers, key=lambda item: (item[1], item[0]))

    @staticmethod
    def _next_heading_line(lines: List[str], start_line: int) -> int:
        in_code_block = False
        for idx in range(start_line + 1, len(lines)):
            line = lines[idx]
            if line.strip().startswith("```"):
                in_code_block = not in_code_block
                continue
            if not in_code_block and re.match(r"^#{1,6}\s+", line):
                return idx
        return len(lines)

    def _insert_fallback_images_near_sections(
        self,
        markdown: str,
        fallback_images: List[Tuple[int, str]],
    ) -> str:
        lines = markdown.rstrip().splitlines()
        markers = self._content_line_markers(markdown)
        if not lines:
            return "\n".join(image for _, image in fallback_images) + "\n"

        if not markers:
            image_lines = ["", "## 原片截图", ""]
            image_lines.extend(image for _, image in fallback_images)
            return markdown.rstrip() + "\n\n" + "\n".join(image_lines).rstrip() + "\n"

        inserts: dict[int, List[str]] = {}
        for ts, image_line in fallback_images:
            marker = next((item for item in reversed(markers) if item[1] <= ts), None)
            if marker is None:
                marker = markers[0]
            insert_line = self._next_heading_line(lines, marker[0])
            inserts.setdefault(insert_line, []).append(image_line)

        output: List[str] = []
        for idx, line in enumerate(lines):
            if idx in inserts:
                if output and output[-1].strip():
                    output.append("")
                output.extend(inserts[idx])
                output.append("")
            output.append(line)

        if len(lines) in inserts:
            if output and output[-1].strip():
                output.append("")
            output.extend(inserts[len(lines)])

        return "\n".join(output).rstrip() + "\n"

    @staticmethod
    def _filter_screenshot_matches_by_structure(
        markdown: str,
        matches: List[Tuple[str, int]],
        plans: List[VisualSectionPlan],
    ) -> Tuple[str, List[Tuple[str, int]]]:
        if not plans:
            for marker, _ts in matches:
                markdown = markdown.replace(marker, "", 1)
            return markdown, []

        selected_indexes = set()
        for plan in plans:
            candidates = [
                (idx, marker, ts)
                for idx, (marker, ts) in enumerate(matches)
                if idx not in selected_indexes and max(0, plan.start - 45) <= ts <= plan.end + 15
            ]
            if not candidates:
                continue
            chosen_idx, _marker, _ts = min(candidates, key=lambda item: abs(item[2] - plan.start))
            selected_indexes.add(chosen_idx)

        allowed = [
            item for idx, item in enumerate(matches)
            if idx in selected_indexes
        ]
        for idx, (marker, _ts) in enumerate(matches):
            if idx not in selected_indexes:
                markdown = markdown.replace(marker, "", 1)
        return markdown, allowed

    @staticmethod
    def _clean_heading_title(line: str) -> str:
        line = re.sub(r"^#{1,6}\s*", "", line).strip()
        line = re.sub(r"\*?Content-\[(?:\d{2}:)?\d{2}:\d{2}\]", "", line)
        line = re.sub(r"\*?Content-\[\d{2}:\d{2}\]", "", line)
        return line.strip(" -")

    @staticmethod
    def _visual_keyword_score(text: str) -> Tuple[float, List[str]]:
        text = re.sub(r"\*?Screenshot-\[(?:\d{2}:)?\d{2}:\d{2}\]\*?", "", text)
        keyword_groups = [
            (2.2, ["架构图", "流程图", "示意图", "关系图", "拓扑图", "时序图", "脑图", "图表", "表格"]),
            (1.8, ["界面", "页面", "屏幕", "窗口", "控制台", "终端", "IDE", "编辑器", "运行结果"]),
            (1.6, ["代码", "公式", "命令", "配置", "参数", "报错", "日志"]),
            (1.4, ["实操", "演示", "操作", "步骤", "案例", "示例", "实验"]),
            (1.2, ["图中", "这张图", "这个表", "这张表", "这个流程", "这段代码", "如下图"]),
            (1.2, ["diagram", "table", "chart", "architecture", "flow", "ui", "screen", "code", "formula", "demo"]),
        ]
        lowered = text.lower()
        score = 0.0
        reasons: List[str] = []
        for weight, keywords in keyword_groups:
            for keyword in keywords:
                haystack = lowered if keyword.isascii() else text
                needle = keyword.lower() if keyword.isascii() else keyword
                count = haystack.count(needle)
                if count:
                    score += weight * min(count, 3)
                    reasons.append(keyword)
        return score, reasons

    @staticmethod
    def _section_anchor_times(start: int, end: int, count: int) -> List[int]:
        count = max(1, min(count, 4))
        section_duration = max(1, end - start)
        if count == 1:
            ratios = [0.18]
        elif count == 2:
            ratios = [0.25, 0.65]
        elif count == 3:
            ratios = [0.18, 0.50, 0.82]
        else:
            ratios = [0.14, 0.38, 0.62, 0.86]
        return [start + max(6, min(section_duration - 1, int(section_duration * ratio))) for ratio in ratios]

    @staticmethod
    def _spread_anchor_times(times: List[int], count: int, min_gap: int = 45) -> List[int]:
        ordered = sorted(set(times))
        if not ordered:
            return []
        count = max(1, min(count, len(ordered), 4))
        if count == 1:
            return [ordered[0]]

        selected: List[int] = []
        for idx in range(count):
            source_idx = round(idx * (len(ordered) - 1) / (count - 1))
            candidate = ordered[source_idx]
            if selected and candidate - selected[-1] < min_gap:
                later = next((item for item in ordered[source_idx:] if item - selected[-1] >= min_gap), None)
                if later is None:
                    continue
                candidate = later
            selected.append(candidate)
        return selected or [ordered[0]]

    def _plan_visual_screenshots(
        self,
        markdown: str,
        duration: Optional[float],
    ) -> List[VisualSectionPlan]:
        lines = markdown.splitlines()
        markers = self._content_line_markers(markdown)
        if not markers:
            markers = self._heading_line_markers_from_screenshots(markdown)
        if not markers:
            logger.info("未找到可用时间标记，跳过结构化截图规划")
            return []

        plans: List[VisualSectionPlan] = []
        total_duration = int(duration or 0)
        for idx, (line_index, start) in enumerate(markers):
            next_line = markers[idx + 1][0] if idx + 1 < len(markers) else len(lines)
            next_time = markers[idx + 1][1] if idx + 1 < len(markers) else total_duration
            if next_time <= start:
                next_time = start + 60

            title = self._clean_heading_title(lines[line_index] if line_index < len(lines) else "")
            body = "\n".join(lines[line_index:next_line])
            section_duration = max(0, next_time - start)
            score, reasons = self._visual_keyword_score(f"{title}\n{body}")

            if re.search(r"```|`[^`]+`", body):
                score += 1.3
                reasons.append("code-block")
            if section_duration >= 180 and score >= 1.2:
                score += 0.8
                reasons.append("long-visual-section")
            if title and any(word in title for word in ["目录", "总结", "AI总结", "参考", "结论"]):
                score -= 2.0

            if score >= 2.0:
                screenshot_times = [ts for _marker, ts in extract_screenshot_timestamps(body)]
                code_block_count = max(0, body.count("```") // 2)
                subsection_count = len(re.findall(r"^#{3,6}\s+", body, flags=re.MULTILINE))

                target_count = 1
                if score >= 5.0 and (section_duration >= 150 or len(screenshot_times) >= 3 or code_block_count >= 1):
                    target_count = 2
                if score >= 6.0 and section_duration >= 240 and subsection_count >= 2:
                    target_count = max(target_count, 2)
                if score >= 8.0 and (
                    section_duration >= 360
                    or len(screenshot_times) >= 6
                    or code_block_count >= 2
                    or subsection_count >= 2
                ):
                    target_count = 3
                if score >= 12.0 and (
                    section_duration >= 600
                    or len(screenshot_times) >= 10
                    or code_block_count >= 3
                    or subsection_count >= 3
                ):
                    target_count = 4

                section_anchor_times = self._section_anchor_times(start, next_time, target_count)
                anchor_times = (
                    self._spread_anchor_times(screenshot_times + section_anchor_times, target_count)
                    if screenshot_times
                    else section_anchor_times
                )
                for anchor_idx, anchor_time in enumerate(anchor_times):
                    ts = anchor_time
                    if total_duration:
                        ts = max(1, min(total_duration - 1, ts))
                    plan_end = anchor_times[anchor_idx + 1] if anchor_idx + 1 < len(anchor_times) else next_time
                    if total_duration:
                        plan_end = max(ts + 1, min(total_duration - 1, plan_end))
                    plans.append(VisualSectionPlan(
                        title=title,
                        start=ts,
                        end=plan_end,
                        score=score,
                        reasons=reasons[:6],
                        line_index=line_index,
                    ))

        filtered: List[VisualSectionPlan] = []
        min_gap = 45
        for plan in sorted(plans, key=lambda item: (-item.score, item.start)):
            if any(abs(plan.start - kept.start) < min_gap for kept in filtered):
                continue
            filtered.append(plan)

        filtered.sort(key=lambda item: item.start)
        logger.info(
            "结构化截图规划完成: %s",
            [{"title": item.title, "start": item.start, "score": round(item.score, 2), "reasons": item.reasons}
             for item in filtered],
        )
        return filtered

    def _best_screenshot_near_timestamp(
        self,
        video_path: Path,
        timestamp: int,
        duration: Optional[float],
        index: int,
        visual_reader: VideoReader,
        search_end: Optional[int] = None,
        gpt: Optional[GPT] = None,
        section_title: str = "",
        section_context: str = "",
    ) -> Optional[FrameCandidate]:
        total_duration = int(duration or 0)
        offsets = [0, 4, 8, 14, 22, 34, 50]
        if search_end and search_end > timestamp:
            span = search_end - timestamp
            sampled_span = min(span, 120)
            offsets.extend([
                max(0, int(sampled_span * ratio))
                for ratio in (0.25, 0.5, 0.75)
            ])
            offsets.append(max(0, min(span - 2, sampled_span)))
        else:
            remaining = max(0, total_duration - timestamp - 1) if total_duration else 90
            sampled_span = min(remaining, 90)
            offsets.extend([
                max(0, int(sampled_span * ratio))
                for ratio in (0.65, 0.9)
            ])
        candidates: List[FrameCandidate] = []
        seen_ts = set()
        for offset_idx, offset in enumerate(sorted(set(offsets))):
            ts = timestamp + offset
            if total_duration:
                ts = max(1, min(total_duration - 1, ts))
            else:
                ts = max(1, ts)
            if ts in seen_ts:
                continue
            seen_ts.add(ts)
            img_path = generate_screenshot(str(video_path), str(IMAGE_OUTPUT_DIR), ts, index * 10 + offset_idx)
            if not Path(img_path).exists():
                continue
            exact_hash = visual_reader._calculate_file_md5(img_path)
            score, perceptual_hash = visual_reader._score_frame(img_path)
            candidates.append(FrameCandidate(
                path=img_path,
                timestamp=ts,
                score=score,
                exact_hash=exact_hash,
                perceptual_hash=perceptual_hash,
            ))

        if not candidates:
            return None

        build_segments = getattr(visual_reader, "_build_visual_segments", None)
        if build_segments:
            segments = build_segments(candidates)
        else:
            segments = [
                type("_SingleFrameSegment", (), {
                    "start": candidate.timestamp,
                    "end": candidate.timestamp,
                    "representative": candidate,
                    "frames": [candidate],
                    "duration": 0,
                })()
                for candidate in candidates
            ]
        if not segments:
            return None

        first_ts = min(segment.start for segment in segments)
        last_ts = max(segment.end for segment in segments)
        best_raw_score = max(segment.representative.score for segment in segments)

        def selection_score(segment) -> float:
            candidate = segment.representative
            if last_ts <= first_ts:
                later_ratio = 0.0
            else:
                later_ratio = (segment.end - first_ts) / (last_ts - first_ts)
            stable_bonus = min(len(segment.frames) - 1, 4) * 0.07 + min(segment.duration / 30, 1) * 0.12
            singleton_penalty = 0.22 if len(segment.frames) == 1 and len(segments) > 1 else 0.0
            completeness_bonus = 0.0
            # For build-up slides/screens, the earliest useful frame is often an
            # incomplete intermediate state. Prefer a later stable state when it
            # is visually close in quality, but do not let a late blank frame win.
            if candidate.score >= max(0.34, best_raw_score - 0.22):
                completeness_bonus += later_ratio * 0.24
                if len(segment.frames) > 1 and later_ratio >= 0.45:
                    completeness_bonus += 0.12
            return candidate.score + stable_bonus + completeness_bonus - singleton_penalty

        best_segment = max(segments, key=selection_score)
        heuristic_best = best_segment.representative
        reviewed_best = self._review_screenshot_candidates(
            candidates,
            gpt,
            section_title=section_title,
            section_context=section_context,
        )
        best = reviewed_best or heuristic_best
        for candidate in candidates:
            if candidate.path != best.path:
                Path(candidate.path).unlink(missing_ok=True)
        if best.score < 0.34:
            Path(best.path).unlink(missing_ok=True)
            return None
        return best

    @staticmethod
    def _fallback_sampling_interval(duration: Optional[float]) -> int:
        if not duration or duration <= 0:
            return 8
        max_sample_windows = 360
        adaptive_interval = max(1, int((duration + max_sample_windows - 1) // max_sample_windows))
        if duration <= 10 * 60:
            return max(6, adaptive_interval)
        if duration <= 30 * 60:
            return max(10, adaptive_interval)
        if duration <= 60 * 60:
            return max(15, adaptive_interval)
        return max(20, adaptive_interval)

    def _fallback_screenshot_timestamps(self, video_path: Path, duration: Optional[float]) -> List[int]:
        try:
            with tempfile.TemporaryDirectory(prefix="bilinote_visual_") as tmp_dir:
                tmp_path = Path(tmp_dir)
                reader = VideoReader(
                    video_path=str(video_path),
                    frame_interval=self._fallback_sampling_interval(duration),
                    frame_dir=str(tmp_path / "frames"),
                    grid_dir=str(tmp_path / "grids"),
                )
                timestamps = reader.extract_representative_timestamps()
                if timestamps:
                    return timestamps
        except Exception as exc:
            logger.warning(f"视觉截图兜底失败，改用均匀时间点: {exc}")

        return self._fallback_uniform_timestamps(duration)

    @staticmethod
    def _fallback_uniform_timestamps(duration: Optional[float]) -> List[int]:
        if not duration or duration <= 0:
            return [20, 60, 120]
        total = int(duration)
        # 避开片头片尾，取中间 3 个位置
        candidates = [int(total * 0.2), int(total * 0.5), int(total * 0.8)]
        deduped = sorted({max(1, min(total - 1, t)) for t in candidates})
        return deduped

    @staticmethod
    def _extract_screenshot_timestamps(markdown: str) -> List[Tuple[str, int]]:
        """
        从 Markdown 文本中提取所有 '*Screenshot-mm:ss' 或 'Screenshot-[mm:ss]' 标记，
        返回 [(原始标记文本, 时间戳秒数), ...] 列表。

        :param markdown: 原始 Markdown 文本
        :return: 标记与对应时间戳秒数的列表
        """
        return extract_screenshot_timestamps(markdown)

    def _save_metadata(self, video_id: str, platform: str, task_id: str) -> None:
        """
        将生成的笔记任务记录插入数据库

        :param video_id: 视频 ID
        :param platform: 平台标识
        :param task_id: 任务 ID
        """
        try:
            insert_video_task(video_id=video_id, platform=platform, task_id=task_id)
            logger.info(f"已保存任务记录到数据库 (video_id={video_id}, platform={platform}, task_id={task_id})")
        except Exception as e:
            logger.error(f"保存任务记录失败：{e}")
