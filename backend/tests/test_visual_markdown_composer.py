import pathlib
import sys
from types import SimpleNamespace


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.visual_markdown_composer import MarkdownComposerHooks, VisualMarkdownComposer


def _composer(markers=None):
    return VisualMarkdownComposer(
        MarkdownComposerHooks(
            content_line_markers=lambda _markdown: list(markers or []),
            next_heading_line=lambda lines, start: next(
                (
                    idx
                    for idx in range(start + 1, len(lines))
                    if lines[idx].startswith("## ")
                ),
                len(lines),
            ),
        )
    )


def _frame(score):
    return SimpleNamespace(score=score)


def test_insert_images_at_document_lines_keeps_later_positions_stable():
    markdown = (
        "## Demo *Content-[00:00]\n"
        "line 1\n"
        "line 2 result\n"
        "line 3\n"
        "line 4 code\n"
        "line 5\n"
    )

    result = VisualMarkdownComposer.insert_images_at_document_lines(
        markdown,
        [
            (3, "![](/static/screenshots/first.jpg)"),
            (5, "![](/static/screenshots/second.jpg)"),
        ],
    )

    assert result.index("first.jpg") < result.index("line 3")
    assert result.index("second.jpg") > result.index("line 4 code")
    assert result.index("second.jpg") < result.index("line 5")


def test_fallback_images_insert_near_content_markers():
    markdown = (
        "## 第一部分 *Content-[00:10]\n"
        "这里讲第一部分。\n\n"
        "## 第二部分 *Content-[01:00]\n"
        "这里讲第二部分。\n"
    )
    composer = _composer(markers=[(0, 10), (3, 60)])

    result = composer.insert_fallback_images_near_sections(
        markdown,
        [(12, "![](/static/screenshots/a.jpg)"), (70, "![](/static/screenshots/b.jpg)")],
    )

    assert result.index("a.jpg") < result.index("## 第二部分")
    assert result.index("b.jpg") > result.index("## 第二部分")
    assert "## 原片截图" not in result


def test_line_placement_filter_collapses_same_anchor_but_keeps_text_separated_anchors():
    markdown = (
        "## Demo\n"
        "The first screen shows provider configuration.\n"
        "This paragraph has enough concrete explanation between the two screenshots.\n"
        "The final screen shows returned rows and verification output.\n"
    )

    kept, skipped = VisualMarkdownComposer.filter_line_placements_by_anchor(
        markdown,
        [
            (2, 10, "![](first.jpg)", "first.jpg", _frame(0.8)),
            (4, 40, "![](second.jpg)", "second.jpg", _frame(0.8)),
        ],
    )

    assert [item[3] for item in kept] == ["first.jpg", "second.jpg"]
    assert skipped == []


def test_published_image_filter_collapses_adjacent_images_and_keeps_later_when_close_score():
    markdown = (
        "## Demo\n"
        "Useful explanation for a visual result.\n"
        "![](early.jpg)\n"
        "![](late.jpg)\n"
    )
    early = (10, "![](early.jpg)", "early.jpg", _frame(0.84))
    late = (20, "![](late.jpg)", "late.jpg", _frame(0.82))

    result_markdown, kept, skipped = VisualMarkdownComposer.filter_published_images_by_context(
        markdown,
        [early, late],
    )

    assert "late.jpg" in result_markdown
    assert "early.jpg" not in result_markdown
    assert kept == [late]
    assert skipped == [early]
