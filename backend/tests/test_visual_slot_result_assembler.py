import pathlib
import shutil
import sys
from types import SimpleNamespace


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

TEST_TMP_ROOT = ROOT / ".test_tmp"

from app.services.visual_markdown_composer import MarkdownComposerHooks, VisualMarkdownComposer
from app.services.visual_slot_result_assembler import VisualSlotResultAssembler, cleanup_paths
from app.utils.video_reader import FrameCandidate


def _composer():
    return VisualMarkdownComposer(
        MarkdownComposerHooks(
            content_line_markers=lambda _markdown: [],
            next_heading_line=lambda lines, _start: len(lines),
        )
    )


def _assembler():
    return VisualSlotResultAssembler(
        _composer(),
        lambda image_path: f"/static/screenshots/{pathlib.Path(image_path).name}",
    )


def _slot_result(slot_id, candidate=None, error=None, plan=None, marker=None, mode="fallback"):
    slot = SimpleNamespace(
        slot_id=slot_id,
        mode=mode,
        timestamp=getattr(candidate, "timestamp", 0),
        index=slot_id,
        marker=marker,
        plan=plan,
    )
    return SimpleNamespace(
        slot=slot,
        candidate=candidate,
        generated_paths=[candidate.path] if candidate else [],
        error=error,
        selection_report={"candidate_count": 2} if candidate else None,
    )


def _plan(insert_line):
    return SimpleNamespace(
        title="Demo",
        start=0,
        end=60,
        section_start=0,
        section_end=60,
        score=4.0,
        reasons=["result"],
        line_index=0,
        insert_line=insert_line,
        insert_reason="document-anchor",
    )


def _candidate(path, timestamp, score=0.9, exact_hash=None):
    return FrameCandidate(
        path=path,
        timestamp=timestamp,
        score=score,
        exact_hash=exact_hash or path,
        perceptual_hash=timestamp,
    )


def test_assembler_inserts_planned_images_and_builds_slot_reports():
    markdown = (
        "## Demo *Content-[00:00]\n"
        "The UI screen shows provider configuration.\n"
        "The final result appears here.\n"
    )

    result = _assembler().assemble(
        markdown,
        [_slot_result(0, _candidate("first.jpg", 12), plan=_plan(2))],
        is_same_visual_state=lambda _left, _right: False,
    )

    assert "first.jpg" in result.markdown
    assert result.successful_slots == 1
    assert result.failed_slots == 0
    assert result.duplicate_slots == 0
    assert result.published_images[0][2] == "first.jpg"
    assert result.visual_report["slots"][0]["status"] == "inserted"
    assert result.visual_report["slots"][0]["selection"]["candidate_count"] == 2


def test_assembler_removes_failed_marker_and_reports_error():
    markdown = (
        "## Demo *Content-[00:00]\n"
        "Visual section.\n"
        "*Screenshot-[00:10]\n"
    )

    result = _assembler().assemble(
        markdown,
        [_slot_result(0, error="no usable screenshot", marker="*Screenshot-[00:10]", mode="marker")],
        is_same_visual_state=lambda _left, _right: False,
    )

    assert "*Screenshot" not in result.markdown
    assert result.failed_slots == 1
    assert result.successful_slots == 0
    assert result.diagnostics == ["marker_failed:0:no usable screenshot"]
    assert result.visual_report["slots"][0]["status"] == "failed"


def test_assembler_skips_failed_optional_fallback_without_marking_failure():
    markdown = "## Demo *Content-[00:00]\nVisual section.\n"

    result = _assembler().assemble(
        markdown,
        [_slot_result(0, error="low quality candidate", mode="fallback")],
        is_same_visual_state=lambda _left, _right: False,
    )

    assert result.markdown == markdown
    assert result.failed_slots == 0
    assert result.skipped_slots == 1
    assert result.successful_slots == 0
    assert result.diagnostics == ["fallback_skipped:0:low quality candidate"]
    assert result.visual_report["slots"][0]["status"] == "skipped"


def test_assembler_marks_duplicate_visual_state_for_cleanup():
    first = _candidate("first.jpg", 10, exact_hash="same")
    duplicate = _candidate("duplicate.jpg", 20, exact_hash="same")

    result = _assembler().assemble(
        "## Demo\nVisual section.\n",
        [_slot_result(0, first), _slot_result(1, duplicate)],
        is_same_visual_state=lambda left, right: left.exact_hash == right.exact_hash,
    )

    assert result.successful_slots == 1
    assert result.duplicate_slots == 1
    assert result.cleanup_paths == ["duplicate.jpg"]
    assert result.visual_report["slots"][1]["status"] == "duplicate"


def test_cleanup_paths_keeps_generation_success_when_cleanup_fails():
    import uuid

    test_dir = TEST_TMP_ROOT / f"cleanup_paths_{uuid.uuid4().hex}"
    locked_like_path = test_dir / "directory-not-file"
    try:
        locked_like_path.mkdir(parents=True)

        cleanup_paths([str(locked_like_path)])

        assert locked_like_path.exists()
    finally:
        shutil.rmtree(test_dir, ignore_errors=True)
