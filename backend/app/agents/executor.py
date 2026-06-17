import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from app.agents.base import AgentRole, ExecutionPlan, StepExecutionMode
from app.agents.note_agents import (
    ChatIndexRequest,
    DownloadAgent,
    DownloadRequest,
    MarkdownComposeRequest,
    MarkdownComposerAgent,
    NoteWriteRequest,
    NoteWriterAgent,
    TranscriptAgent,
    TranscriptResolveRequest,
)
from app.enmus.task_status_enums import TaskStatus
from app.models.audio_model import AudioDownloadResult
from app.models.notes_model import NoteResult
from app.models.transcriber_model import TranscriptResult
from app.services.visual_screenshot_agent import VisualScreenshotState

logger = logging.getLogger(__name__)


@dataclass
class AgentRuntimeContext:
    task_id: str
    video_url: str
    platform: str
    quality: Any
    formats: list[str]
    wants_screenshot: bool
    wants_link: bool
    note_output_dir: Path
    downloader: Any
    gpt: Any
    output_path: Optional[str] = None
    style: Optional[str] = None
    extras: Optional[str] = None
    video_understanding: bool = False
    video_interval: int = 0
    grid_size: list[int] = field(default_factory=list)
    defer_screenshots: bool = False
    audio_cache_file: Optional[Path] = None
    transcript_cache_file: Optional[Path] = None
    markdown_cache_file: Optional[Path] = None
    transcript: Optional[TranscriptResult] = None
    audio_meta: Optional[AudioDownloadResult] = None
    markdown: Optional[str] = None
    video_path: Optional[Path] = None
    video_img_urls: list[str] = field(default_factory=list)
    visual_state: Optional[VisualScreenshotState] = None
    visual_slot_results: list[Any] = field(default_factory=list)
    result: Optional[NoteResult] = None
    diagnostics: list[str] = field(default_factory=list)

    def __post_init__(self):
        self.audio_cache_file = self.audio_cache_file or self.note_output_dir / f"{self.task_id}_audio.json"
        self.transcript_cache_file = self.transcript_cache_file or self.note_output_dir / f"{self.task_id}_transcript.json"
        self.markdown_cache_file = self.markdown_cache_file or self.note_output_dir / f"{self.task_id}_markdown.md"


class PlanExecutor:
    """Executes note-generation plans against concrete agents.

    The planner describes what should happen; this executor is the single place
    that translates those steps into runtime state transitions.
    """

    def __init__(
        self,
        download_agent: DownloadAgent,
        transcript_agent: TranscriptAgent,
        note_writer_agent: NoteWriterAgent,
        markdown_composer_agent: MarkdownComposerAgent,
        chat_rag_agent: Optional[Any] = None,
        status_updater: Optional[Callable[[str, TaskStatus, Optional[str]], None]] = None,
    ):
        self.download_agent = download_agent
        self.transcript_agent = transcript_agent
        self.note_writer_agent = note_writer_agent
        self.markdown_composer_agent = markdown_composer_agent
        self.chat_rag_agent = chat_rag_agent
        self.status_updater = status_updater

    def run(self, plan: ExecutionPlan, context: AgentRuntimeContext) -> AgentRuntimeContext:
        executed: set[str] = set()
        pending = list(plan.steps)
        optional_steps = {step.step_id for step in plan.steps if step.optional}

        while pending:
            ready = [
                step for step in pending
                if all(dependency in executed for dependency in step.depends_on)
            ]
            if not ready:
                unresolved = ", ".join(step.step_id for step in pending)
                raise RuntimeError(f"Agent execution plan has unresolved dependencies: {unresolved}")

            parallel_steps = [step for step in ready if step.mode == StepExecutionMode.PARALLEL]
            immediate_steps = [step for step in ready if step.mode != StepExecutionMode.PARALLEL]

            for step in immediate_steps:
                pending.remove(step)
                try:
                    if step.mode == StepExecutionMode.BACKGROUND:
                        self._handle_background_step(step.step_id, step.agent.role, context)
                    else:
                        self._execute_step(step.step_id, step.agent.role, context)
                except Exception as exc:
                    if not step.optional:
                        raise
                    logger.warning("Optional agent step failed (%s): %s", step.step_id, exc)
                    context.diagnostics.append(f"{step.step_id}: optional step failed: {exc}")
                    self._mark_dependents_executed(step.step_id, pending, executed, optional_steps)
                executed.add(step.step_id)

            if parallel_steps:
                for step in parallel_steps:
                    pending.remove(step)
                with ThreadPoolExecutor(max_workers=min(len(parallel_steps), 8)) as executor:
                    futures = {
                        executor.submit(self._execute_step, step.step_id, step.agent.role, context): step
                        for step in parallel_steps
                    }
                    for future in as_completed(futures):
                        step = futures[future]
                        try:
                            future.result()
                        except Exception as exc:
                            if not step.optional:
                                raise
                            logger.warning("Optional parallel agent step failed (%s): %s", step.step_id, exc)
                            context.diagnostics.append(f"{step.step_id}: optional step failed: {exc}")
                            self._mark_dependents_executed(step.step_id, pending, executed, optional_steps)
                        executed.add(step.step_id)

        context.result = NoteResult(
            markdown=context.markdown or "",
            transcript=context.transcript,
            audio_meta=context.audio_meta,
            gpt=context.gpt,
        )
        return context

    @staticmethod
    def _mark_dependents_executed(
        failed_step_id: str,
        pending: list[Any],
        executed: set[str],
        optional_steps: set[str],
    ) -> None:
        """Skip optional steps that can only run after a failed optional dependency."""
        skipped = {failed_step_id}
        changed = True
        while changed:
            changed = False
            for step in list(pending):
                if step.step_id not in optional_steps:
                    continue
                if any(dependency in skipped for dependency in step.depends_on):
                    pending.remove(step)
                    skipped.add(step.step_id)
                    executed.add(step.step_id)
                    changed = True

    def _handle_background_step(self, step_id: str, role: AgentRole, context: AgentRuntimeContext) -> None:
        if step_id == "compose_markdown" and context.wants_link:
            self._compose_markdown(context, formats=["link"])
            context.diagnostics.append(f"{step_id}: link composition completed during base generation")
            return
        context.diagnostics.append(f"{step_id}: scheduled outside base generation")

    def _execute_step(self, step_id: str, role: AgentRole, context: AgentRuntimeContext) -> None:
        if context.defer_screenshots and step_id in {"select_frames", "review_frames"}:
            context.diagnostics.append(f"{step_id}: deferred with background visual enhancement")
            return
        if step_id == "download":
            self._download(context)
            return
        if step_id == "transcript":
            self._resolve_transcript(context)
            return
        if step_id == "write_markdown":
            self._write_markdown(context)
            return
        if step_id == "plan_visuals":
            self._plan_visuals(context)
            return
        if step_id == "select_frames":
            self._select_frames(context)
            return
        if step_id == "review_frames":
            context.diagnostics.append("review_frames: handled during frame selection")
            return
        if step_id == "compose_markdown":
            formats = []
            if context.wants_link:
                formats.append("link")
            if context.wants_screenshot:
                formats.append("screenshot")
            self._compose_markdown(context, formats=formats)
            return
        if step_id == "index_chat" and self.chat_rag_agent:
            self.chat_rag_agent.run(ChatIndexRequest(task_id=context.task_id))
            return
        logger.info("Skip unsupported plan step %s (%s)", step_id, role)

    def _download(self, context: AgentRuntimeContext) -> None:
        if context.transcript is None:
            context.transcript = self.transcript_agent.load_cached_or_platform_subtitles(
                video_url=context.video_url,
                downloader=context.downloader,
                transcript_cache_file=context.transcript_cache_file,
            )

        need_full_download = self.download_agent.needs_full_download(
            has_transcript=context.transcript is not None,
            wants_screenshot=context.wants_screenshot,
            video_understanding=context.video_understanding,
        )
        context.audio_meta = self.download_agent.run(
            DownloadRequest(
                video_url=context.video_url,
                platform=context.platform,
                quality=context.quality,
                audio_cache_file=context.audio_cache_file,
                downloader=context.downloader,
                output_path=context.output_path,
                screenshot=context.wants_screenshot,
                video_understanding=context.video_understanding,
                video_interval=context.video_interval,
                grid_size=context.grid_size,
                skip_download=not need_full_download,
            )
        )
        context.video_path = getattr(self.download_agent, "video_path", None)
        context.video_img_urls = list(getattr(self.download_agent, "video_img_urls", []) or [])

    def _resolve_transcript(self, context: AgentRuntimeContext) -> None:
        if context.transcript is not None:
            return
        if context.audio_meta is None:
            raise RuntimeError("Cannot transcribe before media metadata is available")
        context.transcript = self.transcript_agent.resolve(
            TranscriptResolveRequest(
                video_url=context.video_url,
                audio_file=context.audio_meta.file_path,
                transcript_cache_file=context.transcript_cache_file,
                downloader=context.downloader,
                task_id=context.task_id,
            )
        )

    def _write_markdown(self, context: AgentRuntimeContext) -> None:
        if context.audio_meta is None or context.transcript is None:
            raise RuntimeError("Cannot write markdown before media and transcript are ready")
        if context.video_understanding and context.video_img_urls and not getattr(context.gpt, "supports_vision", False):
            logger.warning("当前模型不支持视觉输入，视频理解截图将不会发送给模型")
        context.markdown = self.note_writer_agent.run(
            NoteWriteRequest(
                task_id=context.task_id,
                audio_meta=context.audio_meta,
                transcript=context.transcript,
                gpt=context.gpt,
                markdown_cache_file=context.markdown_cache_file,
                link=context.wants_link,
                screenshot=context.wants_screenshot,
                formats=context.formats,
                style=context.style,
                extras=context.extras,
                video_img_urls=context.video_img_urls,
            )
        )

    def _plan_visuals(self, context: AgentRuntimeContext) -> None:
        if not context.markdown:
            raise RuntimeError("Cannot plan screenshots before markdown is ready")
        if not context.video_path:
            raise RuntimeError("截图已启用，但没有可用的视频文件")
        agent = self.markdown_composer_agent.screenshot_agent()
        state = VisualScreenshotState(
            markdown=context.markdown,
            video_path=context.video_path,
            duration=context.audio_meta.duration if context.audio_meta else None,
            gpt=context.gpt,
            transcript_segments=context.transcript.segments if context.transcript else [],
        )
        state.execution_engine = "plan-executor"
        state = agent.prepare_state(state)
        state = agent.filter_marker_node(state)
        state = agent.plan_slots_node(state)
        context.visual_state = state

    def _select_frames(self, context: AgentRuntimeContext) -> None:
        if context.visual_state is None:
            self._plan_visuals(context)
        state = context.visual_state
        slots = state.slots or []
        if not slots:
            context.visual_slot_results = []
            return

        max_workers = min(max(1, len(slots)), 8)
        results: list[Any] = []
        agent = self.markdown_composer_agent.screenshot_agent()
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(agent.process_screenshot_slot, state, slot) for slot in slots]
            for future in as_completed(futures):
                results.append(future.result())
        context.visual_slot_results = sorted(results, key=lambda item: item.slot.slot_id)

    def _compose_markdown(self, context: AgentRuntimeContext, formats: list[str]) -> None:
        if not formats:
            return
        if context.markdown is None or context.audio_meta is None:
            raise RuntimeError("Cannot compose markdown before base note is ready")

        if formats == ["link"] or "screenshot" not in formats:
            context.markdown = self.markdown_composer_agent.run(
                MarkdownComposeRequest(
                    markdown=context.markdown,
                    video_path=context.video_path,
                    formats=formats,
                    audio_meta=context.audio_meta,
                    platform=context.platform,
                    gpt=context.gpt,
                    transcript_segments=context.transcript.segments if context.transcript else [],
                )
            )
            return

        if context.visual_state is None:
            self._plan_visuals(context)
        if context.visual_slot_results == [] and (context.visual_state.slots or []):
            self._select_frames(context)

        agent = self.markdown_composer_agent.screenshot_agent()
        visual_reader = agent.create_visual_reader(context.visual_state.video_path)
        agent.apply_screenshot_slot_results(context.visual_state, context.visual_slot_results, visual_reader)
        context.markdown = context.visual_state.markdown
        if "link" in formats:
            context.markdown = self.markdown_composer_agent.run(
                MarkdownComposeRequest(
                    markdown=context.markdown,
                    video_path=context.video_path,
                    formats=["link"],
                    audio_meta=context.audio_meta,
                    platform=context.platform,
                    gpt=context.gpt,
                    transcript_segments=context.transcript.segments if context.transcript else [],
                )
            )
