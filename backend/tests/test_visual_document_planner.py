import pathlib
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.visual_document_planner import (
    DocumentPlannerHooks,
    DocumentVisualNeedPlanner,
    VisualSectionAnalysis,
    VisualSectionPlan,
)
from app.services.visual_inventory_agent import VisualSceneCandidate


def _hooks() -> DocumentPlannerHooks:
    return DocumentPlannerHooks(
        content_line_markers=lambda _markdown: [(0, 10), (4, 80)],
        heading_line_markers_from_screenshots=lambda _markdown: [],
        transcript_segments_to_windows=lambda _segments: [(10, 30, "UI code result"), (80, 110, "plain talk")],
        infer_section_markers_from_headings=lambda *_args: [],
        clean_heading_title=lambda line: line.replace("##", "").split("*Content")[0].strip(),
        align_section_to_transcript=lambda _title, _body, _windows, start, end: (start, end, "aligned text", 0.2),
        visual_keyword_score=lambda text: (5.0, ["code"]) if "code" in text.lower() else (0.5, []),
        visual_scenes_for_section=lambda scenes, start, end: [
            scene for scene in scenes if start <= scene.representative_ts < end
        ],
        suggested_screenshot_count=lambda *_args, **_kwargs: 2,
        map_visual_lines_to_times=lambda *_args, **_kwargs: [(2, 16), (3, 24)],
        choose_section_insert_lines=lambda _lines, start_line, _end_line, count: [start_line + 1] * count,
        format_visual_inventory_context=lambda scenes: "\n".join(str(scene.representative_ts) for scene in scenes),
        timestamp_in_window=lambda timestamp, start, end: start <= timestamp < end,
        section_anchor_times=lambda start, _end, _count: [start + 5, start + 15],
        spread_anchor_times=lambda times, count, _min_gap: sorted(times)[:count],
        adaptive_min_gap=lambda *_args: 4,
    )


def test_document_planner_analyzes_visual_sections_from_markdown_and_inventory():
    planner = DocumentVisualNeedPlanner(_hooks())
    markdown = (
        "## Build UI *Content-[00:10]\n"
        "This section has code and final result.\n"
        "Use the screen to verify the output.\n\n"
        "## Plain summary *Content-[01:20]\n"
        "This is mostly narration.\n"
    )
    scenes = [
        VisualSceneCandidate(start=12, end=20, representative_ts=16, score=0.7, reasons=["ui"]),
        VisualSceneCandidate(start=88, end=95, representative_ts=90, score=0.2, reasons=["talking"]),
    ]

    analyses = planner.analyze_sections(markdown, 120, visual_inventory=scenes)

    assert len(analyses) == 1
    assert isinstance(analyses[0], VisualSectionAnalysis)
    assert analyses[0].title == "Build UI"
    assert analyses[0].suggested_count == 2
    assert analyses[0].visual_line_times == [(2, 16), (3, 24)]
    assert "可用视频画面" in analyses[0].body


def test_document_planner_creates_ordered_plans_with_document_anchors():
    planner = DocumentVisualNeedPlanner(_hooks())
    markdown = (
        "## Build UI *Content-[00:10]\n"
        "This section has code and final result.\n"
        "Use the screen to verify the output.\n"
    )

    plans = planner.plan(markdown, 120)

    assert len(plans) == 2
    assert all(isinstance(plan, VisualSectionPlan) for plan in plans)
    assert [plan.start for plan in plans] == [16, 24]
    assert [plan.insert_line for plan in plans] == [2, 3]
    assert all(plan.insert_reason == "document-anchor" for plan in plans)
