import json
import logging
import os
from pathlib import Path
from typing import List, Optional, Union

from pydantic import HttpUrl
from dotenv import load_dotenv

from app.downloaders.base import Downloader
from app.db.video_task_dao import delete_task_by_video, insert_video_task
from app.enmus.exception import NoteErrorEnum, ProviderErrorEnum
from app.enmus.task_status_enums import TaskStatus
from app.enmus.note_enums import DownloadQuality
from app.exceptions.note import NoteError
from app.exceptions.provider import ProviderError
from app.gpt.base import GPT
from app.gpt.gpt_factory import GPTFactory
from app.agents import AgentExecutionContext, build_note_execution_plan
from app.agents.executor import AgentRuntimeContext, PlanExecutor
from app.agents.note_agents import (
    AgentRuntimeServices,
    ChatRagAgent,
    MarkdownComposerAgent,
    DownloadAgent,
    NoteWriterAgent,
    TranscriptAgent,
)
from app.models.model_config import ModelConfig
from app.models.notes_model import NoteResult
from app.services.constant import SUPPORT_PLATFORM_MAP
from app.services.provider import ProviderService
from app.services.visual_screenshot_agent import (
    VisualScreenshotAgent,
)
from app.transcriber.base import Transcriber
from app.transcriber.transcriber_provider import get_transcriber, _transcribers
from app.utils.note_helper import prepend_source_link
from app.utils.task_status_writer import write_status_record
from app.utils.video_helper import generate_screenshot
from app.utils.video_reader import VideoReader

# ------------------ 环境变量与全局配置 ------------------

# 从 .env 文件中加载环境变量
load_dotenv()


# 输出目录（用于缓存音频、转写、Markdown 文件，以及存储截图）
NOTE_OUTPUT_DIR = Path(os.getenv("NOTE_OUTPUT_DIR", "note_results"))
NOTE_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
IMAGE_OUTPUT_DIR = os.getenv("OUT_DIR", "./static/screenshots")
# 图片基础 URL（用于生成 Markdown 中的图片链接，需前端静态目录对应）
IMAGE_BASE_URL = os.getenv("IMAGE_BASE_URL", "/static/screenshots")

# 日志配置
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class NoteGenerator:
    """
    NoteGenerator 用于执行视频/音频下载、转写、GPT 生成笔记、插入截图/链接、
    以及将任务信息写入状态文件与数据库等功能。
    """

    def __init__(self, generation_token: Optional[str] = None):
        from app.services.transcriber_config_manager import TranscriberConfigManager
        config_manager = TranscriberConfigManager()
        self.model_size: str = config_manager.get_whisper_model_size()
        self.device: Optional[str] = None
        self.transcriber_type: str = config_manager.get_transcriber_type()
        self.transcriber: Transcriber = self._init_transcriber()
        self.generation_token = generation_token
        self.video_path: Optional[Path] = None
        self.video_img_urls=[]
        self.execution_plan = None
        self.agent_services = AgentRuntimeServices(
            update_status=self._update_status,
            handle_exception=self._handle_exception,
            get_downloader=self._get_downloader,
            transcribe_audio=lambda audio_file: self.transcriber.transcript(file_path=audio_file),
            create_screenshot_agent=self._visual_screenshot_agent,
        )
        self.download_agent = DownloadAgent(self.agent_services)
        self.transcript_agent = TranscriptAgent(self.agent_services)
        self.note_writer_agent = NoteWriterAgent(self.agent_services)
        self.markdown_composer_agent = MarkdownComposerAgent(self.agent_services)
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
        defer_screenshots: bool = False,
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
        formats = _format or []
        format_set = set(formats)
        wants_screenshot = screenshot or "screenshot" in format_set
        wants_link = link or "link" in format_set
        self.execution_plan = build_note_execution_plan(
            AgentExecutionContext(
                task_id=task_id,
                video_url=str(video_url),
                platform=platform,
                quality=quality,
                model_name=model_name,
                provider_id=provider_id,
                formats=tuple(formats),
                screenshot=wants_screenshot,
                link=wants_link,
                has_prefetched_transcript=bool(
                    task_id and (NOTE_OUTPUT_DIR / f"{task_id}_transcript.json").exists()
                ),
                video_understanding=video_understanding,
                defer_screenshots=defer_screenshots,
                review_mode=os.getenv("SCREENSHOT_REVIEW_MODE", "off").strip().lower(),
                metadata={
                    "video_interval": video_interval,
                    "grid_size": grid_size,
                    "style": style,
                    "extras": extras,
                },
            )
        )
        try:
            logger.info(f"开始生成笔记 (task_id={task_id})")
            self._update_status(task_id, TaskStatus.PARSING)
            downloader = self._get_downloader(platform)
            gpt = self._get_gpt(model_name, provider_id)
            logger.info(
                "Agent execution plan for task_id=%s: %s",
                task_id,
                " -> ".join(self.execution_plan.step_ids()),
            )

            runtime_context = AgentRuntimeContext(
                task_id=task_id,
                video_url=str(video_url),
                platform=platform,
                quality=quality,
                formats=formats,
                wants_screenshot=wants_screenshot,
                wants_link=wants_link,
                note_output_dir=NOTE_OUTPUT_DIR,
                downloader=downloader,
                gpt=gpt,
                output_path=output_path,
                style=style,
                extras=extras,
                video_understanding=video_understanding,
                video_interval=video_interval,
                grid_size=grid_size,
                defer_screenshots=defer_screenshots,
            )

            executor = PlanExecutor(
                download_agent=self.download_agent,
                transcript_agent=self.transcript_agent,
                note_writer_agent=self.note_writer_agent,
                markdown_composer_agent=self.markdown_composer_agent,
                chat_rag_agent=ChatRagAgent(),
            )
            runtime_context = executor.run(self.execution_plan, runtime_context)
            markdown = prepend_source_link(runtime_context.markdown or "", str(video_url))
            audio_meta = runtime_context.audio_meta
            transcript = runtime_context.transcript
            self.video_path = runtime_context.video_path
            self.video_img_urls = runtime_context.video_img_urls

            if self.video_path and not getattr(audio_meta, "video_path", None):
                audio_meta.video_path = str(self.video_path)

            self._update_status(task_id, TaskStatus.SAVING)
            self._save_metadata(video_id=audio_meta.video_id, platform=platform, task_id=task_id)

            if not defer_screenshots:
                self._update_status(task_id, TaskStatus.SUCCESS)
            logger.info(f"笔记生成成功 (task_id={task_id})")
            return NoteResult(markdown=markdown, transcript=transcript, audio_meta=audio_meta, gpt=gpt)

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

    # ---------------- 基础设施方法 ----------------

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
        # SUPPORT_PLATFORM_MAP 存放的是已实例化的下载器对象，直接取用即可
        downloader = SUPPORT_PLATFORM_MAP.get(platform)
        logger.debug(f"获取下载器 -  {platform}")
        if not downloader:
            logger.error(f"不支持的平台：{platform}")
            raise NoteError(code=NoteErrorEnum.PLATFORM_NOT_SUPPORTED.code,
                            message=NoteErrorEnum.PLATFORM_NOT_SUPPORTED.message)

        logger.info(f"使用下载器：{downloader.__class__.__name__}")
        return downloader

    def _update_status(self, task_id, status, message: Optional[str] = None):
        write_status_record(
            task_id=task_id,
            status=status,
            message=message,
            generation_token=self.generation_token,
            output_dir=NOTE_OUTPUT_DIR,
        )

    def _handle_exception(self, task_id, exc):
        logger.error(f"任务异常 (task_id={task_id})", exc_info=True)
        error_message = getattr(exc, 'detail', str(exc))
        if isinstance(error_message, dict):
            try:
                error_message = json.dumps(error_message, ensure_ascii=False)
            except Exception:
                error_message = str(error_message)
        self._update_status(task_id, TaskStatus.FAILED, message=error_message)

    def _visual_screenshot_agent(self) -> VisualScreenshotAgent:
        return VisualScreenshotAgent(
            image_output_dir=IMAGE_OUTPUT_DIR,
            image_base_url=IMAGE_BASE_URL,
            video_reader_cls=VideoReader,
            screenshot_func=generate_screenshot,
        )

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
