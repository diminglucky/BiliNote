import json
import logging
from dataclasses import dataclass
from dataclasses import asdict
from pathlib import Path
from typing import Any, Callable, Optional

from app.enmus.note_enums import DownloadQuality
from app.enmus.task_status_enums import TaskStatus
from app.gpt.base import GPT
from app.models.audio_model import AudioDownloadResult
from app.models.transcriber_model import TranscriptResult
from app.models.transcriber_model import TranscriptSegment

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DownloadRequest:
    video_url: str
    platform: str
    quality: DownloadQuality
    audio_cache_file: Path
    downloader: Optional[Any] = None
    output_path: Optional[str] = None
    screenshot: bool = False
    video_understanding: bool = False
    video_interval: int = 0
    grid_size: Optional[list[int]] = None
    skip_download: bool = False


@dataclass(frozen=True)
class TranscriptRequest:
    video_url: str
    audio_file: str
    transcript_cache_file: Path
    downloader: object
    task_id: Optional[str] = None


@dataclass(frozen=True)
class TranscriptResolveRequest:
    video_url: str
    audio_file: str
    transcript_cache_file: Path
    downloader: object
    task_id: Optional[str] = None


@dataclass(frozen=True)
class NoteWriteRequest:
    audio_meta: AudioDownloadResult
    transcript: TranscriptResult
    gpt: GPT
    markdown_cache_file: Path
    link: bool = False
    screenshot: bool = False
    formats: Optional[list[str]] = None
    style: Optional[str] = None
    extras: Optional[str] = None
    video_img_urls: Optional[list[str]] = None


@dataclass(frozen=True)
class MarkdownComposeRequest:
    markdown: str
    video_path: Optional[Path]
    formats: list[str]
    audio_meta: AudioDownloadResult
    platform: str
    gpt: Optional[GPT] = None
    on_markdown_update: Optional[Any] = None
    transcript_segments: Optional[list[Any]] = None


@dataclass(frozen=True)
class ChatIndexRequest:
    task_id: str


@dataclass(frozen=True)
class VisualEnhancementRequest:
    task_id: str
    note: Any
    platform: str
    enhance_token: str
    generation_token: Optional[str] = None
    gpt: Optional[Any] = None


class DownloadAgent:
    def __init__(self, generator):
        self.generator = generator

    @staticmethod
    def needs_full_download(
        has_transcript: bool,
        wants_screenshot: bool,
        video_understanding: bool,
    ) -> bool:
        return (not has_transcript) or wants_screenshot or video_understanding

    def run(self, request: DownloadRequest) -> AudioDownloadResult | None:
        downloader = request.downloader or self.generator._get_downloader(request.platform)
        return self.generator._download_media(
            downloader=downloader,
            video_url=request.video_url,
            quality=request.quality,
            audio_cache_file=request.audio_cache_file,
            status_phase=TaskStatus.DOWNLOADING,
            platform=request.platform,
            output_path=request.output_path,
            screenshot=request.screenshot,
            video_understanding=request.video_understanding,
            video_interval=request.video_interval,
            grid_size=request.grid_size or [],
            skip_download=request.skip_download,
        )


class TranscriptAgent:
    def __init__(self, generator):
        self.generator = generator

    def resolve(self, request: TranscriptResolveRequest) -> TranscriptResult | None:
        transcript = self.load_cached_or_platform_subtitles(
            video_url=request.video_url,
            downloader=request.downloader,
            transcript_cache_file=request.transcript_cache_file,
        )
        if transcript is not None:
            return transcript
        return self.run(
            TranscriptRequest(
                video_url=request.video_url,
                audio_file=request.audio_file,
                transcript_cache_file=request.transcript_cache_file,
                downloader=request.downloader,
                task_id=request.task_id,
            )
        )

    def load_cached_or_platform_subtitles(
        self,
        video_url: str,
        downloader: Any,
        transcript_cache_file: Path,
    ) -> TranscriptResult | None:
        if transcript_cache_file.exists():
            try:
                data = json.loads(transcript_cache_file.read_text(encoding="utf-8"))
                segments = [TranscriptSegment(**seg) for seg in data.get("segments", [])]
                return TranscriptResult(
                    language=data.get("language"),
                    full_text=data["full_text"],
                    segments=segments,
                )
            except Exception as exc:
                logger.warning("Load transcript cache failed: %s", exc)

        try:
            transcript = downloader.download_subtitles(video_url)
            if transcript and transcript.segments:
                transcript_cache_file.write_text(
                    json.dumps(asdict(transcript), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                return transcript
            return None
        except Exception as exc:
            logger.warning("Load platform subtitles failed: %s", exc)
            return None

    def run(self, request: TranscriptRequest):
        return self.generator._transcribe_audio(
            audio_file=request.audio_file,
            transcript_cache_file=request.transcript_cache_file,
            status_phase=TaskStatus.TRANSCRIBING,
        )


class NoteWriterAgent:
    def __init__(self, generator):
        self.generator = generator

    def run(self, request: NoteWriteRequest) -> str | None:
        return self.generator._summarize_text(
            audio_meta=request.audio_meta,
            transcript=request.transcript,
            gpt=request.gpt,
            markdown_cache_file=request.markdown_cache_file,
            link=request.link,
            screenshot=request.screenshot,
            formats=request.formats or [],
            style=request.style,
            extras=request.extras,
            video_img_urls=request.video_img_urls or [],
        )


class MarkdownComposerAgent:
    def __init__(self, generator):
        self.generator = generator

    def run(self, request: MarkdownComposeRequest) -> str:
        return self.generator._post_process_markdown(
            markdown=request.markdown,
            video_path=request.video_path,
            formats=request.formats,
            audio_meta=request.audio_meta,
            platform=request.platform,
            gpt=request.gpt,
            on_markdown_update=request.on_markdown_update,
            transcript_segments=request.transcript_segments,
        )


class ChatRagAgent:
    def __init__(self, vector_store_factory=None):
        self.vector_store_factory = vector_store_factory

    def run(self, request: ChatIndexRequest) -> bool:
        factory = self.vector_store_factory
        if factory is None:
            from app.services.vector_store import VectorStoreManager

            factory = VectorStoreManager
        factory().index_task(request.task_id)
        return True


class VisualEnhancementAgent:
    def __init__(
        self,
        executor,
        status_updater: Callable[[str, str, Optional[str], TaskStatus, str], None],
        enhancement_service_factory=None,
    ):
        self.executor = executor
        self.status_updater = status_updater
        self.enhancement_service_factory = enhancement_service_factory

    def submit(self, request: VisualEnhancementRequest):
        video_path = getattr(request.note.audio_meta, "video_path", None)
        if not video_path:
            logger.warning(
                "Skip visual enhancement because video_path is missing (task_id=%s)",
                request.task_id,
            )
            self.status_updater(
                request.task_id,
                request.enhance_token,
                request.generation_token,
                TaskStatus.SUCCESS,
                "Note is ready, but video file is missing so screenshots cannot be enhanced.",
            )
            return None

        video_path = Path(video_path)
        if not video_path.exists():
            logger.warning(
                "Skip visual enhancement because video file does not exist (task_id=%s, video_path=%s)",
                request.task_id,
                video_path,
            )
            self.status_updater(
                request.task_id,
                request.enhance_token,
                request.generation_token,
                TaskStatus.SUCCESS,
                "Note is ready, but video file does not exist so screenshots cannot be enhanced.",
            )
            return None

        service_factory = self.enhancement_service_factory
        if service_factory is None:
            from app.services.visual_enhancement_service import VisualEnhancementService

            service_factory = VisualEnhancementService

        try:
            future = self.executor.submit(
                service_factory().enhance_saved_note,
                request.task_id,
                str(video_path),
                request.note.audio_meta.duration,
                request.platform,
                request.enhance_token,
                request.generation_token,
                request.gpt,
            )
        except Exception as exc:
            logger.exception(
                "Submit visual enhancement failed (task_id=%s)",
                request.task_id,
            )
            self.status_updater(
                request.task_id,
                request.enhance_token,
                request.generation_token,
                TaskStatus.SUCCESS,
                f"Note is ready, but screenshot enhancement could not be submitted: {exc}",
            )
            return None

        def _on_done(done_future):
            try:
                done_future.result()
            except Exception as exc:
                logger.exception(
                    "Visual enhancement worker failed (task_id=%s)",
                    request.task_id,
                )
                self.status_updater(
                    request.task_id,
                    request.enhance_token,
                    request.generation_token,
                    TaskStatus.SUCCESS,
                    f"Note is ready, but screenshot enhancement failed: {exc}",
                )

        future.add_done_callback(_on_done)
        return future
