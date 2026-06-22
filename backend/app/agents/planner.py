from app.agents.base import (
    AgentExecutionContext,
    AgentRole,
    AgentSpec,
    AgentStep,
    ExecutionPlan,
    StepExecutionMode,
)


DOWNLOAD_AGENT = AgentSpec(
    role=AgentRole.DOWNLOAD,
    name="DownloadAgent",
    description="Resolve media metadata and download audio/video when required.",
)
TRANSCRIPT_AGENT = AgentSpec(
    role=AgentRole.TRANSCRIPT,
    name="TranscriptAgent",
    description="Reuse cached or platform subtitles, otherwise transcribe audio.",
)
NOTE_WRITER_AGENT = AgentSpec(
    role=AgentRole.NOTE_WRITER,
    name="NoteWriterAgent",
    description="Generate the base Markdown note from transcript and metadata.",
)
VISUAL_ENHANCEMENT_AGENT = AgentSpec(
    role=AgentRole.VISUAL_ENHANCEMENT,
    name="VisualEnhancementAgent",
    description="Enhance the base Markdown with document-driven screenshots.",
)
MARKDOWN_COMPOSER_AGENT = AgentSpec(
    role=AgentRole.MARKDOWN_COMPOSER,
    name="MarkdownComposerAgent",
    description="Merge screenshots and links back into Markdown.",
)


def build_note_execution_plan(context: AgentExecutionContext) -> ExecutionPlan:
    formats = set(context.formats)
    wants_screenshot = context.screenshot or "screenshot" in formats
    wants_link = context.link or "link" in formats
    wants_video_file = wants_screenshot or context.video_understanding
    diagnostics: list[str] = []
    steps: list[AgentStep] = []

    steps.append(
        AgentStep(
            step_id="download",
            agent=DOWNLOAD_AGENT,
            reason=(
                "Need full video for screenshots/video understanding."
                if wants_video_file
                else "Need media metadata and audio only if subtitles are unavailable."
            ),
            config={"need_video": wants_video_file},
        )
    )

    if context.has_prefetched_transcript:
        diagnostics.append("TranscriptAgent can reuse prefetched transcript cache.")
    steps.append(
        AgentStep(
            step_id="transcript",
            agent=TRANSCRIPT_AGENT,
            depends_on=("download",),
            reason=(
                "Use prefetched transcript cache before platform subtitles or audio transcription."
                if context.has_prefetched_transcript
                else "Get platform subtitles first, then transcribe audio if needed."
            ),
            config={"has_prefetched_transcript": context.has_prefetched_transcript},
        )
    )

    steps.append(
        AgentStep(
            step_id="write_markdown",
            agent=NOTE_WRITER_AGENT,
            depends_on=("transcript",),
            reason="Generate the base readable Markdown note before visual enhancement.",
        )
    )

    if wants_screenshot:
        visual_mode = (
            StepExecutionMode.BACKGROUND
            if context.defer_screenshots
            else StepExecutionMode.SEQUENTIAL
        )
        steps.append(
            AgentStep(
                step_id="visual_enhancement",
                agent=VISUAL_ENHANCEMENT_AGENT,
                mode=visual_mode,
                depends_on=("write_markdown",),
                optional=True,
                reason="Insert useful screenshots through the visual enhancement pipeline.",
                config={
                    "include_links": wants_link,
                    "review_mode": context.review_mode,
                },
            )
        )
        if context.review_mode != "off":
            diagnostics.append(
                f"Vision review mode is {context.review_mode}; handled inside visual enhancement."
            )
        else:
            diagnostics.append("Vision review is disabled by SCREENSHOT_REVIEW_MODE=off.")
    elif wants_link:
        steps.append(
            AgentStep(
                step_id="compose_markdown",
                agent=MARKDOWN_COMPOSER_AGENT,
                depends_on=("write_markdown",),
                reason="Insert timestamp links into Markdown.",
                config={"include_links": True},
            )
        )

    return ExecutionPlan(
        task_id=context.task_id,
        steps=tuple(steps),
        diagnostics=tuple(diagnostics),
    )
