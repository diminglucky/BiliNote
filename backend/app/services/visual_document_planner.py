import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Tuple

from app.services.visual_inventory_agent import VisualSceneCandidate
from app.services.visual_planning_policy import screenshot_content_budget
from app.utils.screenshot_marker import extract_screenshot_timestamps

logger = logging.getLogger(__name__)


@dataclass
class VisualSectionPlan:
    title: str
    start: int
    end: int
    score: float
    reasons: List[str]
    line_index: int
    section_start: int = 0
    section_end: int = 0
    context: str = ""
    insert_line: Optional[int] = None
    insert_reason: str = ""


@dataclass
class VisualSectionAnalysis:
    title: str
    line_index: int
    start: int
    end: int
    score: float
    reasons: List[str]
    screenshot_times: List[int]
    suggested_count: int
    body: str
    insert_lines: List[int]
    visual_line_times: List[Tuple[int, int]]


@dataclass(frozen=True)
class DocumentPlannerHooks:
    content_line_markers: Callable[[str], List[Tuple[int, int]]]
    heading_line_markers_from_screenshots: Callable[[str], List[Tuple[int, int]]]
    transcript_segments_to_windows: Callable[[Optional[List[Any]]], List[Tuple[int, int, str]]]
    infer_section_markers_from_headings: Callable[
        [str, Optional[float], List[Tuple[int, int, str]]],
        List[Tuple[int, int]],
    ]
    clean_heading_title: Callable[[str], str]
    align_section_to_transcript: Callable[
        [str, str, List[Tuple[int, int, str]], int, int],
        Tuple[int, int, str, float],
    ]
    visual_keyword_score: Callable[[str], Tuple[float, List[str]]]
    visual_scenes_for_section: Callable[
        [List[VisualSceneCandidate], int, int],
        List[VisualSceneCandidate],
    ]
    suggested_screenshot_count: Callable[..., int]
    map_visual_lines_to_times: Callable[..., List[Tuple[int, int]]]
    choose_section_insert_lines: Callable[[List[str], int, int, int], List[int]]
    format_visual_inventory_context: Callable[[List[VisualSceneCandidate]], str]
    timestamp_in_window: Callable[[int, int, int], bool]
    section_anchor_times: Callable[[int, int, int], List[int]]
    spread_anchor_times: Callable[[List[int], int, int], List[int]]
    adaptive_min_gap: Callable[[int, int, int, int], int]


class DocumentVisualNeedPlanner:
    """Plans where the written note needs visual evidence from the video."""

    def __init__(
        self,
        hooks: DocumentPlannerHooks,
        section_analysis_cls: type = VisualSectionAnalysis,
        section_plan_cls: type = VisualSectionPlan,
    ):
        self.hooks = hooks
        self.section_analysis_cls = section_analysis_cls
        self.section_plan_cls = section_plan_cls

    def analyze_sections(
        self,
        markdown: str,
        duration: Optional[float],
        transcript_segments: Optional[List[Any]] = None,
        visual_inventory: Optional[List[VisualSceneCandidate]] = None,
    ) -> List[Any]:
        lines = markdown.splitlines()
        markers = self.hooks.content_line_markers(markdown)
        if not markers:
            markers = self.hooks.heading_line_markers_from_screenshots(markdown)
        transcript_windows = self.hooks.transcript_segments_to_windows(transcript_segments)
        if not markers and transcript_windows:
            markers = self.hooks.infer_section_markers_from_headings(markdown, duration, transcript_windows)
        if not markers:
            logger.info("No usable timestamp markers or transcript alignment; skip document-driven screenshot planning")
            return []

        analyses: List[Any] = []
        total_duration = int(duration or 0)
        for idx, (line_index, start) in enumerate(markers):
            next_line = markers[idx + 1][0] if idx + 1 < len(markers) else len(lines)
            next_time = markers[idx + 1][1] if idx + 1 < len(markers) else total_duration
            if next_time <= start:
                next_time = start + 60

            title = self.hooks.clean_heading_title(lines[line_index] if line_index < len(lines) else "")
            body = "\n".join(lines[line_index:next_line])
            aligned_start, _aligned_end, aligned_context, alignment_score = self.hooks.align_section_to_transcript(
                title,
                body,
                transcript_windows,
                start,
                next_time,
            )
            if alignment_score >= 0.18 and start <= aligned_start < next_time:
                start = aligned_start
                next_time = max(start + 1, next_time)
            score, reasons = self.hooks.visual_keyword_score(f"{title}\n{body}")
            section_scenes = self.hooks.visual_scenes_for_section(
                visual_inventory or [],
                start,
                next_time,
            )
            strong_visual_scenes = [
                scene for scene in section_scenes
                if scene.score >= float(os.getenv("VISUAL_INVENTORY_SECTION_MIN_SCORE", "0.42"))
            ]

            if re.search(r"```|`[^`]+`", body):
                score += 1.3
                reasons.append("code-block")
            if title and any(word in title for word in ["目录", "总结", "AI总结", "参考", "结论"]):
                score -= 2.0
            if alignment_score >= 0.18:
                score += min(1.2, alignment_score * 2.0)
                reasons.append("transcript-align")
            if strong_visual_scenes:
                score += min(2.0, len(strong_visual_scenes) * 0.5)
                reasons.append("visual-inventory")
                for scene in strong_visual_scenes[:3]:
                    reasons.extend(scene.reasons[:2])

            if score < 2.0 and not strong_visual_scenes:
                continue

            explicit_times = [
                ts for _marker, ts in extract_screenshot_timestamps(body)
                if self.hooks.timestamp_in_window(ts, start, next_time)
            ]
            inventory_times = [scene.representative_ts for scene in strong_visual_scenes]
            screenshot_times = sorted(set(explicit_times + inventory_times))
            code_block_count = max(0, body.count("```") // 2)
            subsection_count = len(re.findall(r"^#{3,6}\s+", body, flags=re.MULTILINE))
            step_count = len(re.findall(r"^\s*(?:[-*+]|\d+[.)])\s+", body, flags=re.MULTILINE))
            suggested_count = self.hooks.suggested_screenshot_count(
                score,
                screenshot_times,
                code_block_count,
                subsection_count,
                step_count,
                visual_candidate_count=len(strong_visual_scenes),
                body_line_count=len([line for line in body.splitlines() if line.strip()]),
            )
            visual_line_times = self.hooks.map_visual_lines_to_times(
                lines,
                line_index,
                next_line,
                start,
                next_time,
                suggested_count,
                transcript_windows=transcript_windows,
                visual_scenes=strong_visual_scenes,
            )
            if visual_line_times and not screenshot_times:
                suggested_count = min(suggested_count, len(visual_line_times))
                visual_line_times = visual_line_times[:suggested_count]
            insert_lines = [line_idx for line_idx, _ts in visual_line_times]
            if not insert_lines:
                insert_lines = self.hooks.choose_section_insert_lines(
                    lines,
                    line_index,
                    next_line,
                    suggested_count,
                )
            inventory_context = self.hooks.format_visual_inventory_context(strong_visual_scenes)
            analyses.append(self.section_analysis_cls(
                title=title,
                line_index=line_index,
                start=start,
                end=next_time,
                score=score,
                reasons=reasons[:6],
                screenshot_times=screenshot_times,
                suggested_count=suggested_count,
                body=(
                    body
                    + ("\n\n相关字幕：\n" + aligned_context if aligned_context else "")
                    + ("\n\n可用视频画面：\n" + inventory_context if inventory_context else "")
                ),
                insert_lines=insert_lines,
                visual_line_times=visual_line_times,
            ))
        return analyses

    def plan(
        self,
        markdown: str,
        duration: Optional[float],
        transcript_segments: Optional[List[Any]] = None,
        visual_inventory: Optional[List[VisualSceneCandidate]] = None,
    ) -> List[Any]:
        analyses = self.analyze_sections(
            markdown,
            duration,
            transcript_segments,
            visual_inventory=visual_inventory,
        )
        if not analyses:
            return []

        plans: List[Any] = []
        total_duration = int(duration or 0)
        for analysis in analyses:
            section_anchor_times = self.hooks.section_anchor_times(
                analysis.start,
                analysis.end,
                analysis.suggested_count,
            )
            if analysis.screenshot_times:
                anchor_source = (
                    analysis.screenshot_times
                    if len(analysis.screenshot_times) >= analysis.suggested_count
                    else analysis.screenshot_times + section_anchor_times
                )
                anchor_times = self.hooks.spread_anchor_times(
                    anchor_source,
                    analysis.suggested_count,
                    self.hooks.adaptive_min_gap(
                        analysis.start,
                        analysis.end,
                        analysis.suggested_count,
                        len(analysis.screenshot_times),
                    ),
                )
            else:
                anchor_times = section_anchor_times

            if analysis.visual_line_times and not analysis.screenshot_times:
                anchor_times = [ts for _line, ts in analysis.visual_line_times[:analysis.suggested_count]]

            for anchor_idx, anchor_time in enumerate(anchor_times):
                ts = anchor_time
                if total_duration:
                    ts = max(1, min(total_duration - 1, ts))
                plan_end = anchor_times[anchor_idx + 1] if anchor_idx + 1 < len(anchor_times) else analysis.end
                if total_duration:
                    plan_end = max(ts + 1, min(total_duration - 1, plan_end))
                insert_line = (
                    analysis.insert_lines[min(anchor_idx, len(analysis.insert_lines) - 1)]
                    if analysis.insert_lines
                    else None
                )
                plans.append(self.section_plan_cls(
                    title=analysis.title,
                    start=ts,
                    end=plan_end,
                    score=analysis.score,
                    reasons=analysis.reasons,
                    line_index=analysis.line_index,
                    section_start=analysis.start,
                    section_end=analysis.end,
                    context=analysis.body[:1800],
                    insert_line=insert_line,
                    insert_reason="document-anchor" if analysis.visual_line_times else "document-section",
                ))

        filtered: List[Any] = []
        plan_limit = screenshot_content_budget(analyses)
        analysis_by_line = {analysis.line_index: analysis for analysis in analyses}
        for plan in sorted(plans, key=lambda item: (-item.score, item.start)):
            analysis = analysis_by_line.get(plan.line_index)
            min_gap = (
                self.hooks.adaptive_min_gap(
                    analysis.start,
                    analysis.end,
                    analysis.suggested_count,
                    len(analysis.screenshot_times),
                )
                if analysis
                else 24
            )
            if any(abs(plan.start - kept.start) < min_gap for kept in filtered):
                continue
            filtered.append(plan)
            if len(filtered) >= plan_limit:
                break

        filtered.sort(key=lambda item: item.start)
        logger.info(
            "Section-driven screenshot plan completed: %s",
            [{"title": item.title, "start": item.start, "score": round(item.score, 2), "reasons": item.reasons}
             for item in filtered],
        )
        return filtered
