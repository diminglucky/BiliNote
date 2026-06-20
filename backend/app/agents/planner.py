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
VISUAL_INVENTORY_AGENT = AgentSpec(
    role=AgentRole.VISUAL_INVENTORY,
    name="VisualInventoryAgent",
    description="Scan the video for useful visual states before document placement.",
)
VISUAL_PLANNER_AGENT = AgentSpec(
    role=AgentRole.VISUAL_PLANNER,
    name="VisualPlannerAgent",
    description="Plan useful screenshot positions from Markdown plus video inventory.",
)
FRAME_SELECTOR_AGENT = AgentSpec(
    role=AgentRole.FRAME_SELECTOR,
    name="FrameSelectorAgent",
    description="Select and score frame candidates for each screenshot slot.",
)
VISION_REVIEW_AGENT = AgentSpec(
    role=AgentRole.VISION_REVIEW,
    name="VisionReviewAgent",
    description="Optionally review ambiguous screenshot candidates with a vision model.",
)
MARKDOWN_COMPOSER_AGENT = AgentSpec(
    role=AgentRole.MARKDOWN_COMPOSER,
    name="MarkdownComposerAgent",
    description="Merge screenshots and links back into Markdown.",
)
CHAT_RAG_AGENT = AgentSpec(
    role=AgentRole.CHAT_RAG,
    name="ChatRagAgent",
    description="Build searchable note/transcript indexes for follow-up Q&A.",
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
        steps.extend(
            [
                AgentStep(
                    step_id="build_visual_inventory",
                    agent=VISUAL_INVENTORY_AGENT,
                    mode=visual_mode,
                    depends_on=("write_markdown",),
                    optional=True,
                    reason="Scan the video for useful visual states before screenshot placement.",
                ),
                AgentStep(
                    step_id="plan_visuals",
                    agent=VISUAL_PLANNER_AGENT,
                    mode=visual_mode,
                    depends_on=("build_visual_inventory",),
                    optional=True,
                    reason="Plan screenshot slots from the generated Markdown and video inventory.",
                ),
                AgentStep(
                    step_id="select_frames",
                    agent=FRAME_SELECTOR_AGENT,
                    mode=StepExecutionMode.PARALLEL,
                    depends_on=("plan_visuals",),
                    optional=True,
                    reason="Process screenshot slots concurrently.",
                    config={"concurrency_scope": "screenshot_slots"},
                ),
            ]
        )
        if context.review_mode != "off":
            steps.append(
                AgentStep(
                    step_id="review_frames",
                    agent=VISION_REVIEW_AGENT,
                    mode=StepExecutionMode.PARALLEL,
                    depends_on=("select_frames",),
                    optional=True,
                    reason=f"Vision review mode is {context.review_mode}.",
                    config={"review_mode": context.review_mode},
                )
            )
        else:
            diagnostics.append("VisionReviewAgent is disabled by SCREENSHOT_REVIEW_MODE=off.")
        composer_dep = "review_frames" if context.review_mode != "off" else "select_frames"
        steps.append(
            AgentStep(
                step_id="compose_markdown",
                agent=MARKDOWN_COMPOSER_AGENT,
                mode=visual_mode,
                depends_on=(composer_dep,),
                optional=True,
                reason="Insert selected screenshots into Markdown.",
                config={"include_links": wants_link},
            )
        )
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

    steps.append(
        AgentStep(
            step_id="index_chat",
            agent=CHAT_RAG_AGENT,
            mode=StepExecutionMode.BACKGROUND,
            depends_on=("write_markdown",),
            optional=True,
            reason="Index note and transcript for follow-up Q&A.",
        )
    )

    return ExecutionPlan(
        task_id=context.task_id,
        steps=tuple(steps),
        diagnostics=tuple(diagnostics),
    )
