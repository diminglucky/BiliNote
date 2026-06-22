import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, List, Tuple

from app.services.visual_markdown_composer import VisualMarkdownComposer
from app.services.visual_screenshot_report import (
    candidate_report,
    mark_slot_report_status,
    slot_report_base,
)

logger = logging.getLogger(__name__)

PublishedImage = Tuple[int, str, str, Any]


@dataclass
class VisualSlotAssemblyResult:
    markdown: str
    generated_image_paths: List[str] = field(default_factory=list)
    published_images: List[PublishedImage] = field(default_factory=list)
    cleanup_paths: List[str] = field(default_factory=list)
    diagnostics: List[str] = field(default_factory=list)
    planned_slots: int = 0
    successful_slots: int = 0
    failed_slots: int = 0
    skipped_slots: int = 0
    duplicate_slots: int = 0
    visual_report: dict[str, Any] = field(default_factory=dict)


class VisualSlotResultAssembler:
    """Turns processed screenshot slots into final Markdown and visual reports."""

    def __init__(
        self,
        markdown_composer: VisualMarkdownComposer,
        image_url: Callable[[str], str],
    ):
        self.markdown_composer = markdown_composer
        self.image_url = image_url

    def assemble(
        self,
        markdown: str,
        results: List[Any],
        is_same_visual_state: Callable[[Any, Any], bool],
    ) -> VisualSlotAssemblyResult:
        output = VisualSlotAssemblyResult(markdown=markdown, planned_slots=len(results))
        inserted_visuals: List[Any] = []
        line_placements: List[Tuple[int, int, str, str, Any]] = []
        fallback_placements: List[PublishedImage] = []
        published_images: List[PublishedImage] = []
        slot_reports: List[dict[str, Any]] = []
        slot_report_by_path: dict[str, dict[str, Any]] = {}

        for result in sorted(results, key=lambda item: item.slot.slot_id):
            output.generated_image_paths.extend(result.generated_paths or [])
            slot = result.slot
            slot_report = slot_report_base(slot)
            if getattr(result, "selection_report", None):
                slot_report["selection"] = result.selection_report

            if result.error or result.candidate is None:
                optional_slot = slot.mode != "marker"
                if optional_slot:
                    output.skipped_slots += 1
                else:
                    output.failed_slots += 1
                slot_report.update({
                    "status": "skipped" if optional_slot else "failed",
                    "reason": result.error or "missing-candidate",
                })
                slot_reports.append(slot_report)
                diagnostic_status = "skipped" if optional_slot else "failed"
                output.diagnostics.append(f"{slot.mode}_{diagnostic_status}:{slot.timestamp}:{result.error}")
                if optional_slot:
                    logger.info(
                        "跳过可选截图 slot (mode=%s timestamp=%s): %s",
                        slot.mode,
                        slot.timestamp,
                        result.error,
                    )
                else:
                    logger.warning(
                        "截图 slot 失败 (mode=%s timestamp=%s): %s",
                        slot.mode,
                        slot.timestamp,
                        result.error,
                    )
                if slot.mode == "marker" and slot.marker:
                    output.markdown = output.markdown.replace(slot.marker, "", 1)
                continue

            candidate = result.candidate
            slot_report.update(candidate_report(candidate))
            if any(is_same_visual_state(prev, candidate) for prev in inserted_visuals):
                output.duplicate_slots += 1
                slot_report.update({
                    "status": "duplicate",
                    "reason": "duplicate-visual-state",
                })
                slot_reports.append(slot_report)
                output.cleanup_paths.append(candidate.path)
                if slot.mode == "marker" and slot.marker:
                    output.markdown = output.markdown.replace(slot.marker, "", 1)
                continue

            inserted_visuals.append(candidate)
            image_markdown = f"![]({self.image_url(candidate.path)})"
            slot_report.update({
                "status": "selected",
                "image_markdown": image_markdown,
                "image_url": self.image_url(candidate.path),
            })
            slot_reports.append(slot_report)
            slot_report_by_path[candidate.path] = slot_report

            if slot.mode == "marker" and slot.marker and slot.plan and slot.plan.insert_line is not None:
                output.markdown = output.markdown.replace(slot.marker, "", 1)
                line_placements.append((
                    slot.plan.insert_line,
                    candidate.timestamp,
                    image_markdown,
                    candidate.path,
                    candidate,
                ))
            elif slot.mode == "marker" and slot.marker:
                output.markdown = output.markdown.replace(slot.marker, image_markdown, 1)
                published_images.append((candidate.timestamp, image_markdown, candidate.path, candidate))
            elif slot.plan and slot.plan.insert_line is not None:
                line_placements.append((
                    slot.plan.insert_line,
                    candidate.timestamp,
                    image_markdown,
                    candidate.path,
                    candidate,
                ))
            else:
                fallback_placements.append((candidate.timestamp, image_markdown, candidate.path, candidate))

        if line_placements:
            line_placements, skipped_placements = self.markdown_composer.filter_line_placements_by_anchor(
                output.markdown,
                line_placements,
            )
            for _line_idx, timestamp, _image_markdown, image_path, _candidate in skipped_placements:
                output.duplicate_slots += 1
                output.diagnostics.append(f"placement_collapsed:{timestamp}")
                mark_slot_report_status(
                    slot_report_by_path,
                    image_path,
                    "collapsed",
                    "placement-collapsed",
                )
                output.cleanup_paths.append(image_path)
            ordered_placements = [
                (line_idx, image_markdown)
                for line_idx, _timestamp, image_markdown, _image_path, _candidate in sorted(
                    line_placements,
                    key=lambda item: (item[0], item[1]),
                )
            ]
            output.markdown = self.markdown_composer.insert_images_at_document_lines(
                output.markdown,
                ordered_placements,
            )
            for _line_idx, timestamp, image_markdown, image_path, candidate in line_placements:
                published_images.append((timestamp, image_markdown, image_path, candidate))

        if fallback_placements:
            output.markdown = self.markdown_composer.insert_fallback_images_near_sections(
                output.markdown,
                [
                    (timestamp, image_markdown)
                    for timestamp, image_markdown, _image_path, _candidate in sorted(
                        fallback_placements,
                        key=lambda item: item[0],
                    )
                ],
            )
            published_images.extend(fallback_placements)

        if published_images:
            output.markdown, published_images, cluster_skipped = (
                self.markdown_composer.filter_published_images_by_context(
                    output.markdown,
                    published_images,
                )
            )
            for timestamp, _image_markdown, image_path, _candidate in cluster_skipped:
                output.duplicate_slots += 1
                output.diagnostics.append(f"image_cluster_collapsed:{timestamp}")
                mark_slot_report_status(
                    slot_report_by_path,
                    image_path,
                    "collapsed",
                    "image-cluster-collapsed",
                )
                output.cleanup_paths.append(image_path)

        for timestamp, image_markdown, image_path, _candidate in published_images:
            output.successful_slots += 1
            mark_slot_report_status(
                slot_report_by_path,
                image_path,
                "inserted",
                None,
            )

        output.published_images = published_images
        output.visual_report = {"slots": slot_reports}
        return output


def cleanup_paths(paths: List[str]) -> None:
    for image_path in paths:
        try:
            Path(image_path).unlink(missing_ok=True)
        except Exception as exc:
            logger.warning("清理未发布截图失败 (%s): %s", image_path, exc)
