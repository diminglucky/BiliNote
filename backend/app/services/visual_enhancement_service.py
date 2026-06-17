import json
import logging
import os
import tempfile
from dataclasses import asdict, is_dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Optional


DEFAULT_NOTE_OUTPUT_DIR = os.getenv("NOTE_OUTPUT_DIR", "note_results")
DEFAULT_IMAGE_OUTPUT_DIR = os.getenv("OUT_DIR", "./static/screenshots")
DEFAULT_IMAGE_BASE_URL = os.getenv("IMAGE_BASE_URL", "/static/screenshots")

logger = logging.getLogger(__name__)


class VisualEnhancementService:
    """Enhances screenshots after the base Markdown note has already been saved."""

    def __init__(
        self,
        note_output_dir: str | Path = DEFAULT_NOTE_OUTPUT_DIR,
        status_writer: Optional[Any] = None,
        screenshot_agent_factory: Optional[Callable[[], Any]] = None,
    ):
        self.note_output_dir = Path(note_output_dir)
        self.status_writer = status_writer
        self.screenshot_agent_factory = screenshot_agent_factory

    def _insert_screenshots(
        self,
        markdown: str,
        video_path: Path,
        duration: Optional[float],
        gpt: Any,
        on_markdown_update: Callable[[str, int, str], None],
        transcript_segments: Optional[list[Any]] = None,
    ) -> str | None:
        if self.screenshot_agent_factory:
            agent = self.screenshot_agent_factory()
        else:
            from app.services.visual_screenshot_agent import VisualScreenshotAgent
            from app.utils.video_helper import generate_screenshot
            from app.utils.video_reader import VideoReader

            agent = VisualScreenshotAgent(
                image_output_dir=DEFAULT_IMAGE_OUTPUT_DIR,
                image_base_url=DEFAULT_IMAGE_BASE_URL,
                video_reader_cls=VideoReader,
                screenshot_func=generate_screenshot,
            )

        try:
            return agent.insert_screenshots(
                markdown,
                video_path,
                duration,
                gpt,
                on_markdown_update=on_markdown_update,
                transcript_segments=transcript_segments,
            )
        except TypeError as exc:
            if "transcript_segments" not in str(exc):
                raise
            return agent.insert_screenshots(
                markdown,
                video_path,
                duration,
                gpt,
                on_markdown_update=on_markdown_update,
            )

    def enhance_saved_note(
        self,
        task_id: str,
        video_path: str | Path,
        duration: Optional[float],
        platform: str,
        enhance_token: Optional[str] = None,
        generation_token: Optional[str] = None,
        gpt: Any = None,
    ) -> bool:
        result_path = self.note_output_dir / f"{task_id}.json"
        inserted_count = 0

        try:
            payload = self._load_result(result_path)
            if not self._matches_token(payload, enhance_token, generation_token):
                logger.info("Skip stale visual enhancement result (task_id=%s)", task_id)
                return False

            if not self._update_status_if_current(
                result_path,
                enhance_token,
                generation_token,
                self.note_output_dir,
                self.status_writer,
                task_id,
                "ENHANCING",
                message="Base note is ready; enhancing key screenshots asynchronously",
            ):
                return False

            markdown = payload.get("markdown") or ""
            transcript_payload = payload.get("transcript") or {}
            transcript_segments = transcript_payload.get("segments") or []
            audio_meta = self._audio_meta_from_payload(payload.get("audio_meta") or {})
            audio_meta.duration = float(duration or audio_meta.duration or 0)
            audio_meta.platform = platform or audio_meta.platform

            def _publish_increment(markdown_snapshot: str, timestamp: int, _image_markdown: str) -> None:
                nonlocal inserted_count
                latest_payload = self._load_result(result_path)
                if not self._matches_token(latest_payload, enhance_token, generation_token):
                    logger.info("Skip stale visual enhancement increment (task_id=%s)", task_id)
                    return
                inserted_count += 1
                latest_payload["markdown"] = markdown_snapshot
                self._atomic_write_json(result_path, latest_payload)
                self._update_status_if_current(
                    result_path,
                    enhance_token,
                    generation_token,
                    self.note_output_dir,
                    self.status_writer,
                    task_id,
                    "ENHANCING",
                    message=f"正在增强截图：已插入 {inserted_count} 张关键截图（最近 {int(timestamp)} 秒）",
                )

            enhanced = self._insert_screenshots(
                markdown=markdown,
                video_path=Path(video_path),
                duration=audio_meta.duration,
                gpt=gpt,
                on_markdown_update=_publish_increment,
                transcript_segments=transcript_segments,
            )

            latest_payload = self._load_result(result_path)
            if not self._matches_token(latest_payload, enhance_token, generation_token):
                logger.info("Skip stale visual enhancement writeback (task_id=%s)", task_id)
                return False

            if not enhanced or enhanced == markdown:
                inserted_after = (enhanced or markdown).count("![](") - markdown.count("![](")
                status_message = (
                    "Note is ready; no additional key screenshot was needed"
                    if inserted_after > 0
                    else "Note is ready, but screenshot enhancement did not find a usable image"
                )
                self._update_status_if_current(
                    result_path,
                    enhance_token,
                    generation_token,
                    self.note_output_dir,
                    self.status_writer,
                    task_id,
                    "SUCCESS",
                    message=status_message,
                )
                return False

            latest_payload["markdown"] = enhanced
            self._atomic_write_json(result_path, latest_payload)
            self._reindex_task(task_id)
            self._update_status_if_current(
                result_path,
                enhance_token,
                generation_token,
                self.note_output_dir,
                self.status_writer,
                task_id,
                "SUCCESS",
                message="Note is ready; key screenshots have been enhanced",
            )
            return True
        except Exception as exc:
            logger.exception("Visual enhancement failed (task_id=%s)", task_id)
            if enhance_token and not self._has_current_token(result_path, enhance_token, generation_token):
                logger.info("Skip stale visual enhancement failure status (task_id=%s)", task_id)
                return False
            if inserted_count > 0:
                self._reindex_task(task_id)
            self._update_status_if_current(
                result_path,
                enhance_token,
                generation_token,
                self.note_output_dir,
                self.status_writer,
                task_id,
                "SUCCESS",
                message=f"Note is ready; screenshot enhancement failed: {exc}",
            )
            return False

    @staticmethod
    def _matches_token(
        payload: dict[str, Any],
        enhance_token: Optional[str],
        generation_token: Optional[str] = None,
    ) -> bool:
        if enhance_token and payload.get("enhance_token") != enhance_token:
            return False
        if generation_token and payload.get("generation_token") != generation_token:
            return False
        return True

    @classmethod
    def _update_status_if_current(
        cls,
        result_path: Path,
        enhance_token: Optional[str],
        generation_token: Optional[str],
        note_output_dir: Path,
        status_writer: Optional[Any],
        task_id: str,
        status: str,
        message: str,
    ) -> bool:
        if enhance_token and not cls._has_current_token(result_path, enhance_token, generation_token):
            logger.info("Skip stale visual enhancement status update (task_id=%s)", task_id)
            return False
        if status_writer:
            status_writer._update_status(task_id, status, message=message)
            return True

        from app.services.note import NoteGenerator

        NoteGenerator.write_status(
            task_id,
            status,
            message=message,
            generation_token=generation_token,
            output_dir=note_output_dir,
        )
        return True

    @staticmethod
    def _load_result(path: Path) -> dict[str, Any]:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("result file is not a JSON object")
        return data

    @staticmethod
    def _audio_meta_from_payload(data: dict[str, Any]):
        return SimpleNamespace(
            file_path=data.get("file_path") or "",
            title=data.get("title") or "",
            duration=float(data.get("duration") or 0),
            cover_url=data.get("cover_url"),
            platform=data.get("platform") or "",
            video_id=data.get("video_id") or "",
            raw_info=data.get("raw_info") or {},
            video_path=data.get("video_path"),
        )

    @staticmethod
    def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            delete=False,
            dir=str(path.parent),
            prefix=f"{path.name}.",
            suffix=".tmp",
        ) as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
            temp_path = Path(f.name)
        temp_path.replace(path)

    @classmethod
    def _has_current_token(
        cls,
        path: Path,
        enhance_token: str,
        generation_token: Optional[str] = None,
    ) -> bool:
        try:
            return cls._matches_token(cls._load_result(path), enhance_token, generation_token)
        except Exception:
            return False

    @staticmethod
    def _reindex_task(task_id: str) -> None:
        try:
            from app.services.vector_store import VectorStoreManager

            VectorStoreManager().index_task(task_id)
        except Exception as exc:
            logger.warning("Failed to reindex after visual enhancement (task_id=%s): %s", task_id, exc)


def note_to_json_payload(note: Any) -> dict[str, Any]:
    def convert(value: Any) -> Any:
        if is_dataclass(value):
            return {key: convert(item) for key, item in asdict(value).items()}
        if isinstance(value, list):
            return [convert(item) for item in value]
        if isinstance(value, dict):
            return {key: convert(item) for key, item in value.items()}
        return value

    return {
        "markdown": note.markdown,
        "transcript": convert(note.transcript),
        "audio_meta": convert(note.audio_meta),
        "enhance_token": getattr(note, "enhance_token", None),
        "generation_token": getattr(note, "generation_token", None),
    }


def result_from_payload(payload: dict[str, Any]):
    transcript_data = payload.get("transcript") or {}
    transcript = SimpleNamespace(
        language=transcript_data.get("language"),
        full_text=transcript_data.get("full_text") or "",
        segments=[
            SimpleNamespace(**segment)
            for segment in transcript_data.get("segments", [])
        ],
        raw=transcript_data.get("raw"),
    )
    audio_meta = VisualEnhancementService._audio_meta_from_payload(payload.get("audio_meta") or {})
    return SimpleNamespace(
        markdown=payload.get("markdown") or "",
        transcript=transcript,
        audio_meta=audio_meta,
    )
