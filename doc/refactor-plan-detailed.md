# VideoNote Agent Refactor Implementation

This document records the implemented architecture after the 2026-06 refactor.
It is not a proposal. The code path described here is the current target shape.

## Goals

- `NoteGenerator` is the orchestrator facade only.
- Concrete work is owned by agents.
- `ExecutionPlan` is executed by `PlanExecutor`, not used as decoration.
- Regeneration creates a new `generation_token` and never returns stale results.
- Screenshot enhancement is asynchronous and incremental.
- A failed optional visual step must not destroy the base Markdown note.

## Backend Architecture

```text
API route
  -> NoteGenerator.generate()
     -> build_note_execution_plan()
     -> PlanExecutor.run()
        -> DownloadAgent
        -> TranscriptAgent
        -> NoteWriterAgent
        -> MarkdownComposerAgent
        -> ChatRagAgent background marker

Saved base note
  -> VisualEnhancementAgent.submit()
     -> VisualEnhancementService.enhance_saved_note()
        -> VisualScreenshotAgent / LangGraph screenshot graph
        -> incremental markdown writeback
```

## Implemented Boundaries

`NoteGenerator` keeps only cross-cutting infrastructure:

- transcriber initialization
- provider/model factory
- downloader factory
- exception serialization
- screenshot-agent factory
- metadata persistence

The old private business pipeline methods were removed:

- `_download_media`
- `_transcribe_audio`
- `_summarize_text`
- `_post_process_markdown`

Agents now own those responsibilities directly.

Agents do not receive the `NoteGenerator` object. They receive
`AgentRuntimeServices`, a narrow dependency bundle containing only the services
they need:

- status writer
- exception handler
- downloader factory
- transcriber adapter
- screenshot-agent factory

This keeps the orchestration facade from becoming a hidden service locator.

Task status persistence is now a standalone utility:

- `backend/app/utils/task_status_writer.py`
- API routes and visual enhancement write status through `write_status_record`
- `NoteGenerator` now calls the same utility internally and no longer exposes status persistence as its own static business API

## Execution Semantics

`PlanExecutor` supports:

- `SEQUENTIAL`: blocking pipeline step
- `PARALLEL`: concurrent step execution
- `BACKGROUND`: base generation records the step as scheduled

Optional steps are isolated. If a visual planning/selection/composition step fails,
the base Markdown can still finish and be saved. Required steps such as download,
transcription, and note writing still fail the task.

When `defer_screenshots=True`, the base note is saved first. Screenshot insertion is
performed by `VisualEnhancementService` after the result file exists, so the user can
see progress while images are added.

## Regeneration Semantics

Regeneration keeps the same `task_id` but creates a fresh `generation_token`.

Before scheduling the new job, the route removes only stale display artifacts:

- `{task_id}.json`
- `{task_id}_markdown.md`

Reusable media caches are intentionally preserved:

- `{task_id}_audio.json`
- `{task_id}_transcript.json`

This makes regeneration real while avoiding repeated download/transcription cost.

Status and result polling always verify the active `generation_token`. Old result files
must not be returned for a newer generation.

## Frontend State Model

Frontend task state is centralized in:

- `src/models/taskStateMachine.ts`
- `src/services/taskApi.ts`
- `src/store/taskStore/index.ts`

Markdown is stored as `Markdown[]`. A generation token maps to one Markdown version.
During screenshot enhancement, incremental updates replace that version instead of
creating multiple fake versions.

Regeneration immediately sets the task to a visible submitting/running state, then
polls only the matching generation token.

## Verification

Current verification targets:

```bash
D:\software\anaconda\envs\play\python.exe -m pytest backend\tests\test_agent_planner.py backend\tests\test_note_agents.py backend\tests\test_visual_screenshot_graph.py backend\tests\test_note_screenshot_fallback.py backend\tests\test_visual_enhancement_service.py backend\tests\test_note_router_cache_recovery.py backend\tests\test_bilibili_video_cache_quality.py backend\tests\test_remote_video_cache_quality.py backend\tests\test_video_reader_quality.py backend\tests\test_screenshot_marker.py -q
```

```bash
cd BillNote_frontend
npm.cmd run build
```
