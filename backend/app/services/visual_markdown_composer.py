import os
import re
from dataclasses import dataclass
from typing import Any, Callable, List, Tuple


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except Exception:
        return default
    return max(minimum, min(maximum, value))


LinePlacement = Tuple[int, int, str, str, Any]
PublishedImage = Tuple[int, str, str, Any]


@dataclass(frozen=True)
class MarkdownComposerHooks:
    content_line_markers: Callable[[str], List[Tuple[int, int]]]
    next_heading_line: Callable[[List[str], int], int]


class VisualMarkdownComposer:
    """Composes selected screenshots into the generated Markdown note."""

    def __init__(self, hooks: MarkdownComposerHooks):
        self.hooks = hooks

    def insert_fallback_images_near_sections(
        self,
        markdown: str,
        fallback_images: List[Tuple[int, str]],
    ) -> str:
        lines = markdown.rstrip().splitlines()
        markers = self.hooks.content_line_markers(markdown)
        if not lines:
            return "\n".join(image for _, image in fallback_images) + "\n"

        if not markers:
            image_lines = ["", "## 原片截图", ""]
            image_lines.extend(image for _, image in fallback_images)
            return markdown.rstrip() + "\n\n" + "\n".join(image_lines).rstrip() + "\n"

        inserts: dict[int, List[str]] = {}
        for ts, image_line in fallback_images:
            marker = next((item for item in reversed(markers) if item[1] <= ts), None)
            if marker is None:
                marker = markers[0]
            insert_line = self.hooks.next_heading_line(lines, marker[0])
            inserts.setdefault(insert_line, []).append(image_line)

        output: List[str] = []
        for idx, line in enumerate(lines):
            if idx in inserts:
                if output and output[-1].strip():
                    output.append("")
                output.extend(inserts[idx])
                output.append("")
            output.append(line)

        if len(lines) in inserts:
            if output and output[-1].strip():
                output.append("")
            output.extend(inserts[len(lines)])

        return "\n".join(output).rstrip() + "\n"

    @staticmethod
    def insert_images_at_document_lines(
        markdown: str,
        placements: List[Tuple[int, str]],
    ) -> str:
        if not placements:
            return markdown

        lines = markdown.rstrip().splitlines()
        if not lines:
            return "\n".join(image for _, image in placements).rstrip() + "\n"

        inserts: dict[int, List[str]] = {}
        for line_idx, image_line in placements:
            safe_idx = max(0, min(len(lines), line_idx))
            inserts.setdefault(safe_idx, []).append(image_line)

        output: List[str] = []
        for idx, line in enumerate(lines):
            output.append(line)
            after_idx = idx + 1
            if after_idx in inserts:
                if output and output[-1].strip():
                    output.append("")
                output.extend(inserts[after_idx])
                output.append("")

        if 0 in inserts:
            prefix: List[str] = []
            prefix.extend(inserts[0])
            if prefix and lines:
                prefix.append("")
            output = prefix + output

        if len(lines) in inserts:
            existing_insert_count = len(inserts[len(lines)])
            if existing_insert_count and output[-existing_insert_count:] == inserts[len(lines)]:
                return "\n".join(output).rstrip() + "\n"

        return "\n".join(output).rstrip() + "\n"

    @classmethod
    def filter_line_placements_by_anchor(
        cls,
        markdown: str,
        placements: List[LinePlacement],
    ) -> Tuple[List[LinePlacement], List[LinePlacement]]:
        if not placements:
            return [], []

        min_line_gap = _env_int("SCREENSHOT_INSERT_LINE_MIN_GAP", 4, 0, 12)
        lines = markdown.splitlines()
        best_by_line: dict[int, LinePlacement] = {}
        skipped: List[LinePlacement] = []
        for placement in sorted(placements, key=lambda item: (item[0], item[1])):
            line_idx = placement[0]
            current_key = next(
                (
                    existing_line
                    for existing_line in sorted(best_by_line)
                    if min_line_gap > 0
                    and abs(line_idx - existing_line) < min_line_gap
                    and not cls.has_heading_between_insert_lines(lines, existing_line, line_idx)
                    and not cls.has_text_between_insert_lines(lines, existing_line, line_idx)
                ),
                line_idx if line_idx in best_by_line else None,
            )
            current = best_by_line.get(current_key) if current_key is not None else None
            if current is None:
                best_by_line[line_idx] = placement
                continue

            chosen = cls.prefer_line_placement(current, placement)
            if chosen is current:
                skipped.append(placement)
            else:
                skipped.append(current)
                if current_key in best_by_line:
                    del best_by_line[current_key]
                best_by_line[line_idx] = placement

        return sorted(best_by_line.values(), key=lambda item: (item[0], item[1])), skipped

    @classmethod
    def filter_published_images_by_context(
        cls,
        markdown: str,
        images: List[PublishedImage],
    ) -> Tuple[str, List[PublishedImage], List[PublishedImage]]:
        if len(images) < 2:
            return markdown, images, []

        lines = markdown.splitlines()
        remaining = list(images)
        image_lines: List[Tuple[int, PublishedImage]] = []
        for line_idx, line in enumerate(lines):
            stripped = line.strip()
            for record_idx, record in enumerate(remaining):
                if stripped == record[1]:
                    image_lines.append((line_idx, record))
                    remaining.pop(record_idx)
                    break

        kept: List[Tuple[int, PublishedImage]] = []
        skipped: List[PublishedImage] = []
        for line_idx, record in image_lines:
            current_idx = next(
                (
                    idx
                    for idx, (kept_line, _kept_record) in enumerate(kept)
                    if not cls.has_heading_between_line_indexes(lines, kept_line, line_idx)
                    and not cls.has_text_between_line_indexes(lines, kept_line, line_idx)
                ),
                None,
            )
            if current_idx is None:
                kept.append((line_idx, record))
                continue

            kept_line, kept_record = kept[current_idx]
            chosen = cls.prefer_published_image(kept_record, record)
            if chosen is kept_record:
                skipped.append(record)
            else:
                skipped.append(kept_record)
                kept[current_idx] = (line_idx, record)

        if not skipped:
            return markdown, images, []

        skipped_remaining = list(skipped)
        output: List[str] = []
        for line in lines:
            stripped = line.strip()
            skip_idx = next(
                (idx for idx, record in enumerate(skipped_remaining) if stripped == record[1]),
                None,
            )
            if skip_idx is not None:
                skipped_remaining.pop(skip_idx)
                continue
            output.append(line)

        kept_images = [record for _line_idx, record in sorted(kept, key=lambda item: item[0])]
        return "\n".join(output).rstrip() + "\n", kept_images, skipped

    @staticmethod
    def prefer_line_placement(current: LinePlacement, candidate: LinePlacement) -> LinePlacement:
        current_frame = current[4]
        candidate_frame = candidate[4]
        if candidate_frame.score > current_frame.score + 0.08:
            return candidate
        if current_frame.score > candidate_frame.score + 0.08:
            return current
        if candidate[1] > current[1]:
            return candidate
        return current

    @staticmethod
    def prefer_published_image(current: PublishedImage, candidate: PublishedImage) -> PublishedImage:
        current_frame = current[3]
        candidate_frame = candidate[3]
        if candidate_frame.score > current_frame.score + 0.08:
            return candidate
        if current_frame.score > candidate_frame.score + 0.08:
            return current
        if candidate[0] > current[0]:
            return candidate
        return current

    @staticmethod
    def has_heading_between_line_indexes(lines: List[str], left_idx: int, right_idx: int) -> bool:
        start = max(0, min(left_idx, right_idx) + 1)
        end = min(len(lines), max(left_idx, right_idx))
        return any(re.match(r"^#{1,6}\s+", lines[idx].strip()) for idx in range(start, end))

    @staticmethod
    def has_text_between_line_indexes(lines: List[str], left_idx: int, right_idx: int) -> bool:
        start = max(0, min(left_idx, right_idx) + 1)
        end = min(len(lines), max(left_idx, right_idx))
        text = "\n".join(
            line.strip()
            for line in lines[start:end]
            if line.strip()
            and not re.match(r"^!\[[^\]]*\]\(", line.strip())
            and not re.match(r"^#{1,6}\s+", line.strip())
        )
        return len(text) >= 30

    @staticmethod
    def has_heading_between_insert_lines(lines: List[str], left_insert: int, right_insert: int) -> bool:
        start = max(0, min(left_insert, right_insert))
        end = min(len(lines), max(left_insert, right_insert))
        return any(re.match(r"^#{1,6}\s+", lines[idx].strip()) for idx in range(start, end))

    @staticmethod
    def has_text_between_insert_lines(lines: List[str], left_insert: int, right_insert: int) -> bool:
        start = max(0, min(left_insert, right_insert))
        end = min(len(lines), max(left_insert, right_insert))
        text = "\n".join(
            line.strip()
            for line in lines[start:end]
            if line.strip()
            and not re.match(r"^!\[[^\]]*\]\(", line.strip())
            and not re.match(r"^#{1,6}\s+", line.strip())
        )
        return len(text) >= 30
