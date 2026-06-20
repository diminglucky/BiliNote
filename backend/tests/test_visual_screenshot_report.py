import pathlib
import sys
from types import SimpleNamespace


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.visual_screenshot_report import (
    candidate_report,
    image_markdown_url,
    mark_slot_report_status,
    slot_report_base,
    summarize_visual_state,
    visual_plan_report,
)


def test_visual_plan_and_slot_report_are_stable_dicts():
    plan = SimpleNamespace(
        title="Demo Section",
        start=10,
        end=40,
        section_start=8,
        section_end=45,
        score=3.45678,
        reasons=["code", "result"],
        line_index=12,
        insert_line=18,
        insert_reason="document-anchor",
    )
    slot = SimpleNamespace(
        slot_id=2,
        mode="fallback",
        timestamp=16,
        marker=None,
        plan=plan,
    )

    assert visual_plan_report(plan) == {
        "title": "Demo Section",
        "start": 10,
        "end": 40,
        "section_start": 8,
        "section_end": 45,
        "score": 3.4568,
        "reasons": ["code", "result"],
        "line_index": 12,
        "insert_line": 18,
        "insert_reason": "document-anchor",
    }
    report = slot_report_base(slot)
    assert report["slot_id"] == 2
    assert report["mode"] == "fallback"
    assert report["section"]["title"] == "Demo Section"


def test_candidate_report_and_status_update():
    candidate = SimpleNamespace(
        timestamp=22,
        score=0.92346,
        path="shot.png",
        exact_hash="abc",
        perceptual_hash=123,
    )
    report = candidate_report(candidate)
    assert report["candidate_timestamp"] == 22
    assert report["candidate_score"] == 0.9235

    by_path = {"shot.png": report}
    mark_slot_report_status(by_path, "shot.png", "inserted")
    assert report["status"] == "inserted"
    mark_slot_report_status(by_path, "shot.png", "collapsed", "image-cluster-collapsed")
    assert report["status"] == "collapsed"
    assert report["reason"] == "image-cluster-collapsed"


def test_summarize_visual_state_includes_report_plans_and_images():
    plan = SimpleNamespace(
        title="Result",
        start=30,
        end=50,
        section_start=20,
        section_end=60,
        score=4,
        reasons=["result"],
        line_index=4,
        insert_line=8,
        insert_reason="document-section",
    )
    state = SimpleNamespace(
        visual_report={"slots": [{"slot_id": 0, "status": "inserted"}]},
        execution_engine="langgraph",
        planned_slot_count=1,
        successful_slot_count=1,
        failed_slot_count=0,
        duplicate_slot_count=0,
        diagnostics=[],
        visual_plans=[plan],
        generated_images=[(32, "![](/static/screenshots/key.png)")],
        published_image_paths=["key.png"],
    )

    summary = summarize_visual_state(state)

    assert summary["execution_engine"] == "langgraph"
    assert summary["slots"][0]["status"] == "inserted"
    assert summary["plans"][0]["title"] == "Result"
    assert summary["images"][0]["url"] == "/static/screenshots/key.png"
    assert image_markdown_url("![](/static/screenshots/key.png)") == "/static/screenshots/key.png"
