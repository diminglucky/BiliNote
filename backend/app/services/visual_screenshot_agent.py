import base64
import json
import logging
import mimetypes
import os
import re
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple, Type

from PIL import Image, ImageFilter, ImageStat

from app.gpt.base import GPT
from app.services.visual_screenshot_graph import run_visual_screenshot_graph
from app.utils.screenshot_marker import extract_screenshot_timestamps, normalize_screenshot_markers
from app.utils.video_helper import generate_screenshot
from app.utils.video_reader import FrameCandidate, VideoReader

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except Exception:
        return default
    return max(minimum, min(maximum, value))


def screenshot_review_mode() -> str:
    """Controls optional multimodal review for screenshot candidates.

    off: use the fast local visual heuristic only.
    balanced: only review high-value or ambiguous selections.
    strict: require the vision model to pick a candidate.
    assist: ask the vision model, but keep the local heuristic if review fails.
    """
    mode = os.getenv("SCREENSHOT_REVIEW_MODE", "off").strip().lower()
    if mode in {"1", "true", "yes", "on", "enabled", "strict"}:
        return "strict"
    if mode in {"balanced", "smart", "auto"}:
        return "balanced"
    if mode in {"assist", "assisted", "optional"}:
        return "assist"
    return "off"


def screenshot_content_budget(items: List[object]) -> int:
    if not items:
        return 0
    total = 0
    for item in items:
        total += max(1, int(getattr(item, "suggested_count", 1)))
    return max(1, min(40, total))


@dataclass
class VisualSectionPlan:
    title: str
    start: int
    end: int
    score: float
    reasons: List[str]
    line_index: int
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


@dataclass
class VisualScreenshotSlot:
    slot_id: int
    mode: str
    timestamp: int
    index: int
    marker: Optional[str] = None
    plan: Optional[VisualSectionPlan] = None


@dataclass
class VisualScreenshotSlotResult:
    slot: VisualScreenshotSlot
    candidate: Optional[FrameCandidate] = None
    generated_paths: Optional[List[str]] = None
    error: Optional[str] = None


@dataclass
class VisualScreenshotState:
    markdown: str
    video_path: Path
    duration: Optional[float] = None
    gpt: Optional[GPT] = None
    transcript_segments: Optional[List[Any]] = None
    matches: Optional[List[Tuple[str, int]]] = None
    visual_plans: Optional[List[VisualSectionPlan]] = None
    slots: Optional[List[VisualScreenshotSlot]] = None
    generated_images: Optional[List[Tuple[int, str]]] = None
    generated_image_paths: Optional[List[str]] = None
    published_image_paths: Optional[List[str]] = None
    diagnostics: Optional[List[str]] = None
    execution_engine: str = "local"
    on_markdown_update: Optional[Callable[[str, int, str], None]] = None


class VisualScreenshotAgent:
    """Plans, selects, reviews, and inserts useful video screenshots into notes."""

    def __init__(
        self,
        image_output_dir: str | Path,
        image_base_url: str,
        video_reader_cls: Type[VideoReader] = VideoReader,
        screenshot_func: Callable[[str, str, int, int], str] = generate_screenshot,
    ):
        self.image_output_dir = Path(image_output_dir)
        self.image_base_url = image_base_url
        self.video_reader_cls = video_reader_cls
        self.screenshot_func = screenshot_func
        self._vision_review_count = 0
        self._vision_review_lock = threading.Lock()
        self._slot_semaphore = threading.Semaphore(
            _env_int("SCREENSHOT_SLOT_CONCURRENCY", 2, 1, 8)
        )

    def insert_screenshots(
        self,
        markdown: str,
        video_path: Path,
        duration: Optional[float] = None,
        gpt: Optional[GPT] = None,
        on_markdown_update: Optional[Callable[[str, int, str], None]] = None,
        transcript_segments: Optional[List[Any]] = None,
    ) -> str | None:
        state = self.run(VisualScreenshotState(
            markdown=markdown,
            video_path=video_path,
            duration=duration,
            gpt=gpt,
            on_markdown_update=on_markdown_update,
            transcript_segments=transcript_segments,
        ))
        return state.markdown

    @staticmethod
    def _section_context(plan: Optional[VisualSectionPlan], markdown: str) -> str:
        if plan is None:
            return ""
        return plan.context or VisualScreenshotAgent.section_context_for_plan(markdown, plan)

    def run(self, state: VisualScreenshotState) -> VisualScreenshotState:
        state.execution_engine = "langgraph"
        try:
            return run_visual_screenshot_graph(self, state)
        except Exception:
            self.cleanup_generated_artifacts(state)
            raise

    def run_nodes_inline(self, state: VisualScreenshotState) -> VisualScreenshotState:
        state.execution_engine = "local"
        state = self.prepare_state(state)
        state = self.filter_marker_node(state)
        state = self.compose_images_node(state)
        return state

    def prepare_state(self, state: VisualScreenshotState) -> VisualScreenshotState:
        if state.diagnostics is None:
            state.diagnostics = []
        state.markdown = normalize_screenshot_markers(state.markdown)
        state.matches = extract_screenshot_timestamps(state.markdown)
        state.visual_plans = self.plan_visual_screenshots(
            state.markdown,
            state.duration,
            transcript_segments=state.transcript_segments,
        )
        state.slots = []
        state.generated_images = []
        state.generated_image_paths = []
        state.published_image_paths = []
        return state

    def filter_marker_node(self, state: VisualScreenshotState) -> VisualScreenshotState:
        matches = state.matches or []
        visual_plans = state.visual_plans or []
        if matches:
            state.markdown, state.matches = self.filter_screenshot_matches_by_structure(
                state.markdown,
                matches,
                visual_plans,
            )
        return state

    def compose_images_node(self, state: VisualScreenshotState) -> VisualScreenshotState:
        if state.slots is None or (
            not state.slots and ((state.matches or []) or (state.visual_plans or []))
        ):
            state.slots = self.plan_screenshot_slots(state)
        visual_reader = self.create_visual_reader(state.video_path)
        results = [
            self.process_screenshot_slot(state, slot)
            for slot in state.slots
        ]
        self.apply_screenshot_slot_results(state, results, visual_reader)
        return state

    def plan_slots_node(self, state: VisualScreenshotState) -> VisualScreenshotState:
        state.slots = self.plan_screenshot_slots(state)
        return state

    def plan_screenshot_slots(self, state: VisualScreenshotState) -> List[VisualScreenshotSlot]:
        matches = state.matches or []
        visual_plans = state.visual_plans or []
        slots: List[VisualScreenshotSlot] = []
        selected_plan_starts: set[int] = set()

        for idx, (marker, ts) in enumerate(matches):
            plan = self.matching_visual_plan(ts, visual_plans)
            if plan:
                selected_plan_starts.add(plan.start)
            slots.append(VisualScreenshotSlot(
                slot_id=len(slots),
                mode="marker",
                timestamp=ts,
                index=idx,
                marker=marker,
                plan=plan,
            ))

        supplement_limit = _env_int(
            "SCREENSHOT_SUPPLEMENT_LIMIT",
            screenshot_content_budget(visual_plans),
            0,
            40,
        )
        if supplement_limit > 0:
            missing_plans = [plan for plan in visual_plans if plan.start not in selected_plan_starts]
            missing_plans = sorted(missing_plans, key=lambda item: (-item.score, item.start))[:supplement_limit]
            missing_plans.sort(key=lambda item: item.start)
            for offset, plan in enumerate(missing_plans):
                slots.append(VisualScreenshotSlot(
                    slot_id=len(slots),
                    mode="fallback",
                    timestamp=plan.start,
                    index=len(matches) + offset,
                    plan=plan,
                ))

        return slots

    def process_screenshot_slot(
        self,
        state: VisualScreenshotState,
        slot: VisualScreenshotSlot,
    ) -> VisualScreenshotSlotResult:
        generated_paths: List[str] = []
        plan = slot.plan
        with self._slot_semaphore:
            try:
                visual_reader = self.create_visual_reader(state.video_path)
                candidate = self.best_screenshot_near_timestamp(
                    video_path=state.video_path,
                    timestamp=slot.timestamp,
                    duration=state.duration,
                    index=slot.index,
                    visual_reader=visual_reader,
                    search_end=plan.end if plan else None,
                    gpt=state.gpt,
                    section_title=plan.title if plan else "",
                    section_context=self._section_context(plan, state.markdown),
                    generated_image_paths=generated_paths,
                )
                if candidate is None:
                    raise RuntimeError(f"未找到可用截图候选: {slot.timestamp}")
                if not Path(candidate.path).exists():
                    raise FileNotFoundError(candidate.path)
                if candidate.score < 0.42:
                    raise RuntimeError(f"截图候选质量过低: {candidate.score:.3f}")
                return VisualScreenshotSlotResult(
                    slot=slot,
                    candidate=candidate,
                    generated_paths=generated_paths,
                )
            except Exception as exc:
                for image_path in generated_paths:
                    try:
                        Path(image_path).unlink(missing_ok=True)
                    except Exception as cleanup_exc:
                        logger.warning("清理失败截图候选失败 (%s): %s", image_path, cleanup_exc)
                return VisualScreenshotSlotResult(
                    slot=slot,
                    generated_paths=generated_paths,
                    error=str(exc),
                )

    def apply_screenshot_slot_results(
        self,
        state: VisualScreenshotState,
        results: List[VisualScreenshotSlotResult],
        visual_reader: VideoReader,
    ) -> None:
        if state.generated_image_paths is None:
            state.generated_image_paths = []
        if state.generated_images is None:
            state.generated_images = []

        inserted_visuals: List[FrameCandidate] = []
        successful_slots = 0

        for result in sorted(results, key=lambda item: item.slot.slot_id):
            state.generated_image_paths.extend(result.generated_paths or [])
            slot = result.slot
            if result.error or result.candidate is None:
                self.add_diagnostic(state, f"{slot.mode}_failed:{slot.timestamp}:{result.error}")
                logger.warning(
                    "截图 slot 失败 (mode=%s timestamp=%s): %s",
                    slot.mode,
                    slot.timestamp,
                    result.error,
                )
                if slot.mode == "marker" and slot.marker:
                    state.markdown = state.markdown.replace(slot.marker, "", 1)
                continue

            candidate = result.candidate
            if any(visual_reader._is_same_visual_state(prev, candidate) for prev in inserted_visuals):
                Path(candidate.path).unlink(missing_ok=True)
                if slot.mode == "marker" and slot.marker:
                    state.markdown = state.markdown.replace(slot.marker, "", 1)
                continue

            inserted_visuals.append(candidate)
            image_markdown = f"![]({self.image_url(candidate.path)})"
            if slot.mode == "marker" and slot.marker:
                state.markdown = state.markdown.replace(slot.marker, image_markdown, 1)
            elif slot.plan and slot.plan.insert_line is not None:
                state.markdown = self.insert_images_at_document_lines(
                    state.markdown,
                    [(slot.plan.insert_line, image_markdown)],
                )
            else:
                state.markdown = self.insert_fallback_images_near_sections(
                    state.markdown,
                    [(candidate.timestamp, image_markdown)],
                )
            state.generated_images.append((candidate.timestamp, image_markdown))
            successful_slots += 1
            if self.publish_incremental_update(state, candidate.timestamp, image_markdown):
                self.mark_published_image(state, candidate.path)

        if not successful_slots and any(result.error for result in results):
            logger.info("截图增强未插入成功截图，保留基础笔记")

    def create_visual_reader(self, video_path: Path) -> VideoReader:
        return self.video_reader_cls(
            video_path=str(video_path),
            frame_dir=str(self.image_output_dir),
            grid_dir=str(self.image_output_dir),
        )
    @staticmethod
    def publish_incremental_update(
        state: VisualScreenshotState,
        timestamp: int,
        image_markdown: str,
    ) -> bool:
        if not state.on_markdown_update:
            return False
        try:
            state.on_markdown_update(state.markdown, timestamp, image_markdown)
            return True
        except Exception as exc:
            logger.warning("增量写回截图失败 (timestamp=%s): %s", timestamp, exc)
            return False

    @staticmethod
    def mark_published_image(state: VisualScreenshotState, image_path: str) -> None:
        if not state.on_markdown_update:
            return
        if state.published_image_paths is None:
            state.published_image_paths = []
        state.published_image_paths.append(image_path)
    @staticmethod
    def cleanup_generated_artifacts(state: VisualScreenshotState) -> None:
        published = set(state.published_image_paths or [])
        for image_path in state.generated_image_paths or []:
            if image_path in published:
                continue
            try:
                Path(image_path).unlink(missing_ok=True)
            except Exception as exc:
                logger.warning("清理截图文件失败 (%s): %s", image_path, exc)

    @staticmethod
    def add_diagnostic(state: VisualScreenshotState, message: str) -> None:
        if state.diagnostics is None:
            state.diagnostics = []
        state.diagnostics.append(message)

    def image_url(self, image_path: str) -> str:
        filename = Path(image_path).name
        return f"{self.image_base_url.rstrip('/')}/{filename}"

    @staticmethod
    def matching_visual_plan(timestamp: int, plans: List[VisualSectionPlan]) -> Optional[VisualSectionPlan]:
        candidates = [
            plan for plan in plans
            if max(0, plan.start - 45) <= timestamp <= plan.end + 15
        ]
        if not candidates:
            return None
        return min(candidates, key=lambda plan: abs(plan.start - timestamp))

    @staticmethod
    def section_context_for_plan(markdown: str, plan: Optional[VisualSectionPlan]) -> str:
        if plan is None:
            return ""
        lines = markdown.splitlines()
        start_line = max(0, plan.line_index)
        end_line = VisualScreenshotAgent.next_heading_line(lines, start_line)
        section = "\n".join(lines[start_line:end_line]).strip()
        return section[:1800]

    @staticmethod
    def image_data_url(path: str) -> str:
        mime_type = mimetypes.guess_type(path)[0] or "image/jpeg"
        with open(path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    @staticmethod
    def extract_json_object(text: str) -> dict | None:
        text = (text or "").strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except Exception:
            pass
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except Exception:
            return None

    @staticmethod
    def format_seconds(seconds: int) -> str:
        seconds = max(0, int(seconds))
        hh = seconds // 3600
        mm = (seconds % 3600) // 60
        ss = seconds % 60
        if hh:
            return f"{hh:02d}:{mm:02d}:{ss:02d}"
        return f"{mm:02d}:{ss:02d}"

    @staticmethod
    def content_line_markers(markdown: str) -> List[Tuple[int, int]]:
        pattern = r"(?:\*?)Content-(?:\[(\d{2}):(\d{2})\]|(\d{2}):(\d{2}))"
        heading_markers: List[Tuple[int, int]] = []
        fallback_markers: List[Tuple[int, int]] = []
        in_code_block = False
        for line_idx, line in enumerate(markdown.splitlines()):
            if line.strip().startswith("```"):
                in_code_block = not in_code_block
                continue
            if in_code_block:
                continue
            stripped = line.lstrip()
            is_heading = bool(re.match(r"^#{1,6}\s+", stripped))
            is_toc_link = bool(re.match(r"^[-*+]\s+\[", stripped))
            for match in re.finditer(pattern, line):
                mm = match.group(1) or match.group(3)
                ss = match.group(2) or match.group(4)
                marker = (line_idx, int(mm) * 60 + int(ss))
                if is_heading:
                    heading_markers.append(marker)
                elif not is_toc_link:
                    fallback_markers.append(marker)
        markers = heading_markers or fallback_markers
        return sorted(markers, key=lambda item: (item[1], item[0]))

    @staticmethod
    def heading_line_markers_from_screenshots(markdown: str) -> List[Tuple[int, int]]:
        lines = markdown.splitlines()
        heading_lines = [
            idx for idx, line in enumerate(lines)
            if re.match(r"^#{1,6}\s+", line) and "目录" not in line and "AI总结" not in line
        ]
        markers: List[Tuple[int, int]] = []
        for pos, line_idx in enumerate(heading_lines):
            next_heading = heading_lines[pos + 1] if pos + 1 < len(heading_lines) else len(lines)
            section = "\n".join(lines[line_idx:next_heading])
            screenshot_matches = extract_screenshot_timestamps(section)
            if screenshot_matches:
                markers.append((line_idx, screenshot_matches[0][1]))
        return sorted(markers, key=lambda item: (item[1], item[0]))

    @staticmethod
    def next_heading_line(lines: List[str], start_line: int) -> int:
        in_code_block = False
        for idx in range(start_line + 1, len(lines)):
            line = lines[idx]
            if line.strip().startswith("```"):
                in_code_block = not in_code_block
                continue
            if not in_code_block and re.match(r"^#{1,6}\s+", line):
                return idx
        return len(lines)

    def insert_fallback_images_near_sections(
        self,
        markdown: str,
        fallback_images: List[Tuple[int, str]],
    ) -> str:
        lines = markdown.rstrip().splitlines()
        markers = self.content_line_markers(markdown)
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
            insert_line = self.next_heading_line(lines, marker[0])
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

    @staticmethod
    def filter_screenshot_matches_by_structure(
        markdown: str,
        matches: List[Tuple[str, int]],
        plans: List[VisualSectionPlan],
    ) -> Tuple[str, List[Tuple[str, int]]]:
        if not plans:
            return markdown, matches

        selected_indexes = set()
        for plan in plans:
            candidates = [
                (idx, marker, ts)
                for idx, (marker, ts) in enumerate(matches)
                if idx not in selected_indexes and max(0, plan.start - 45) <= ts <= plan.end + 15
            ]
            if not candidates:
                continue
            chosen_idx, _marker, _ts = min(candidates, key=lambda item: abs(item[2] - plan.start))
            selected_indexes.add(chosen_idx)

        allowed = [item for idx, item in enumerate(matches) if idx in selected_indexes]
        for idx, (marker, _ts) in enumerate(matches):
            if idx not in selected_indexes:
                markdown = markdown.replace(marker, "", 1)
        return markdown, allowed

    @staticmethod
    def clean_heading_title(line: str) -> str:
        line = re.sub(r"^#{1,6}\s*", "", line).strip()
        line = re.sub(r"\*?Content-\[(?:\d{2}:)?\d{2}:\d{2}\]", "", line)
        line = re.sub(r"\*?Content-\[\d{2}:\d{2}\]", "", line)
        return line.strip(" -")

    @staticmethod
    def _normalize_text_for_match(text: str) -> List[str]:
        tokens = re.findall(r"[A-Za-z][A-Za-z0-9_+-]{2,}|[\u4e00-\u9fff]{2,}", text or "")
        cleaned: List[str] = []
        stopwords = {
            "这个", "一个", "这里", "然后", "就是", "可以", "需要", "进行", "通过",
            "视频", "内容", "部分", "说明", "总结", "背景", "介绍", "the", "and",
            "for", "with", "that", "this", "from", "into", "when", "where",
        }
        for token in tokens:
            token = token.strip().lower()
            if len(token) < 2 or token in stopwords:
                continue
            cleaned.append(token)
            if re.fullmatch(r"[\u4e00-\u9fff]+", token) and len(token) >= 4:
                for size in (2, 3):
                    cleaned.extend(token[idx:idx + size] for idx in range(0, len(token) - size + 1))
        return cleaned

    @staticmethod
    def transcript_segments_to_windows(transcript_segments: Optional[List[Any]]) -> List[Tuple[int, int, str]]:
        windows: List[Tuple[int, int, str]] = []
        for item in transcript_segments or []:
            try:
                if isinstance(item, dict):
                    raw_start = item.get("start")
                    raw_end = item.get("end")
                    raw_text = item.get("text", "")
                else:
                    raw_start = getattr(item, "start", None)
                    raw_end = getattr(item, "end", None)
                    raw_text = getattr(item, "text", "")
                start = int(float(raw_start))
                end = int(float(raw_end if raw_end is not None else start + 1))
                text = str(raw_text).strip()
            except Exception:
                continue
            if not text:
                continue
            windows.append((max(0, start), max(start + 1, end), text))
        return sorted(windows, key=lambda item: item[0])

    @classmethod
    def align_section_to_transcript(
        cls,
        title: str,
        body: str,
        transcript_windows: List[Tuple[int, int, str]],
        fallback_start: int,
        fallback_end: int,
    ) -> Tuple[int, int, str, float]:
        if not transcript_windows:
            return fallback_start, fallback_end, "", 0.0

        query_tokens = cls._normalize_text_for_match(f"{title}\n{body}")
        if not query_tokens:
            return fallback_start, fallback_end, "", 0.0

        query = set(query_tokens[:80])
        scored: List[Tuple[float, int, int, str]] = []
        for idx, (start, end, text) in enumerate(transcript_windows):
            neighborhood = transcript_windows[max(0, idx - 1): min(len(transcript_windows), idx + 2)]
            merged = " ".join(item[2] for item in neighborhood)
            segment_tokens = set(cls._normalize_text_for_match(merged))
            if not segment_tokens:
                continue
            overlap = len(query & segment_tokens)
            if overlap <= 0:
                continue
            score = overlap / max(4, min(len(query), 24))
            scored.append((score, start, end, merged))

        if not scored:
            return fallback_start, fallback_end, "", 0.0

        scored.sort(key=lambda item: (-item[0], item[1]))
        best_score, best_start, _best_end, _merged = scored[0]
        if best_score < 0.18:
            return fallback_start, fallback_end, "", best_score

        nearby = [
            item for item in scored
            if abs(item[1] - best_start) <= 90 and item[0] >= best_score * 0.45
        ]
        start = min(item[1] for item in nearby)
        end = max(item[2] for item in nearby)
        end = max(end, start + 45)
        context = " ".join(item[3] for item in nearby)[:800]
        return start, end, context, best_score

    @staticmethod
    def visual_keyword_score(text: str) -> Tuple[float, List[str]]:
        text = re.sub(r"\*?Screenshot-\[(?:\d{2}:)?\d{2}:\d{2}\]\*?", "", text)
        keyword_groups = [
            (2.2, ["架构图", "流程图", "示意图", "关系图", "拓扑图", "时序图", "脑图", "图表", "表格"]),
            (1.8, ["界面", "页面", "屏幕", "窗口", "控制台", "终端", "IDE", "编辑器", "运行结果"]),
            (1.6, ["代码", "公式", "命令", "配置", "参数", "报错", "日志"]),
            (1.4, ["实操", "演示", "操作", "步骤", "案例", "示例", "实验"]),
            (1.4, ["Agent", "Plan", "Re-Plan", "Execute", "执行计划", "最终结果", "主程序", "工作流", "状态图"]),
            (1.2, ["图中", "这张图", "这个表", "这张表", "这个流程", "这段代码", "如下图"]),
            (1.2, ["diagram", "table", "chart", "architecture", "flow", "ui", "screen", "code", "formula", "demo"]),
        ]
        lowered = text.lower()
        score = 0.0
        reasons: List[str] = []
        for weight, keywords in keyword_groups:
            for keyword in keywords:
                haystack = lowered if keyword.isascii() else text
                needle = keyword.lower() if keyword.isascii() else keyword
                count = haystack.count(needle)
                if count:
                    score += weight * min(count, 3)
                    reasons.append(keyword)
        return score, reasons

    @staticmethod
    def line_visual_score(line: str, in_code_block: bool = False) -> Tuple[float, List[str]]:
        stripped = line.strip()
        if not stripped:
            return 0.0, []
        if re.match(r"^#{1,6}\s+", stripped):
            return 0.0, []
        if "Screenshot-" in stripped or re.match(r"^!\[[^\]]*\]\(", stripped):
            return 0.0, []

        score, reasons = VisualScreenshotAgent.visual_keyword_score(stripped)
        if in_code_block:
            score += 2.4
            reasons.append("code-line")
        if re.match(r"^\s*(?:[-*+]|\d+[.)])\s+", line):
            score += 0.7
            reasons.append("step-line")
        if re.search(r"`[^`]+`", line):
            score += 0.7
            reasons.append("inline-code")
        if any(word in stripped for word in ["最终", "结果", "输出", "成功", "失败", "报错", "验证", "完成"]):
            score += 1.1
            reasons.append("result-line")
        if any(word in stripped for word in ["打开", "点击", "选择", "输入", "运行", "执行", "安装", "配置", "创建"]):
            score += 0.9
            reasons.append("operation-line")
        return score, reasons[:6]

    @classmethod
    def choose_section_insert_lines(
        cls,
        lines: List[str],
        start_line: int,
        end_line: int,
        count: int,
    ) -> List[int]:
        count = max(1, min(count, 4))
        candidates: List[Tuple[float, int, List[str]]] = []
        in_code_block = False
        code_block_start: Optional[int] = None

        for line_idx in range(start_line + 1, end_line):
            line = lines[line_idx]
            if line.strip().startswith("```"):
                if not in_code_block:
                    code_block_start = line_idx
                else:
                    insert_line = line_idx + 1
                    candidates.append((3.4, insert_line, ["code-block-end"]))
                    code_block_start = None
                in_code_block = not in_code_block
                continue

            score, reasons = cls.line_visual_score(line, in_code_block)
            if score <= 0:
                continue
            insert_line = line_idx + 1
            if in_code_block and code_block_start is not None:
                insert_line = line_idx + 1
            candidates.append((score, insert_line, reasons))

        if not candidates:
            return [min(end_line, start_line + 1)]

        candidates.sort(key=lambda item: (-item[0], item[1]))
        selected: List[int] = []
        min_line_gap = 4
        for _score, line_idx, _reasons in candidates:
            if any(abs(line_idx - existing) < min_line_gap for existing in selected):
                continue
            selected.append(line_idx)
            if len(selected) >= count:
                break

        if len(selected) < count:
            for _score, line_idx, _reasons in candidates:
                if line_idx not in selected:
                    selected.append(line_idx)
                if len(selected) >= count:
                    break

        return sorted(selected[:count])

    @staticmethod
    def section_anchor_times(start: int, end: int, count: int) -> List[int]:
        count = max(1, min(count, 4))
        section_duration = max(1, end - start)
        if count == 1:
            ratios = [0.18]
        elif count == 2:
            ratios = [0.25, 0.65]
        elif count == 3:
            ratios = [0.18, 0.50, 0.82]
        else:
            ratios = [0.14, 0.38, 0.62, 0.86]
        return [start + max(6, min(section_duration - 1, int(section_duration * ratio))) for ratio in ratios]

    @staticmethod
    def spread_anchor_times(times: List[int], count: int, min_gap: int = 45) -> List[int]:
        ordered = sorted(set(times))
        if not ordered:
            return []
        count = max(1, min(count, len(ordered), 4))
        if count == 1:
            return [ordered[0]]

        selected: List[int] = []
        for idx in range(count):
            source_idx = round(idx * (len(ordered) - 1) / (count - 1))
            candidate = ordered[source_idx]
            if selected and candidate - selected[-1] < min_gap:
                later = next((item for item in ordered[source_idx:] if item - selected[-1] >= min_gap), None)
                if later is None:
                    continue
                candidate = later
            selected.append(candidate)
        return selected or [ordered[0]]

    @staticmethod
    def adaptive_min_gap(start: int, end: int, suggested_count: int, marker_count: int = 0) -> int:
        duration = max(1, end - start)
        density = max(suggested_count, marker_count, 1)
        if duration <= 90:
            return 8 if density >= 3 else 12
        if duration <= 180:
            return 12 if density >= 3 else 18
        if density >= 4:
            return 18
        if density >= 3:
            return 24
        return 36

    @staticmethod
    def select_candidate_offsets(offsets: List[int], max_candidates: int) -> List[int]:
        ordered = sorted(set(max(0, offset) for offset in offsets))
        if len(ordered) <= max_candidates:
            return ordered

        selected = {ordered[0], ordered[-1]}
        for preferred in (22, 34, 45, 50, 60, 90):
            if preferred in ordered and len(selected) < max_candidates:
                selected.add(preferred)

        remaining_slots = max_candidates - len(selected)
        if remaining_slots > 0:
            interior = [offset for offset in ordered[1:-1] if offset not in selected]
            for idx in range(remaining_slots):
                if not interior:
                    break
                source_idx = round(idx * (len(interior) - 1) / max(1, remaining_slots - 1))
                selected.add(interior[source_idx])
        return sorted(selected)

    @staticmethod
    def non_note_frame_penalty(file_path: str, timestamp: int, duration: Optional[float] = None) -> float:
        """Penalize sparse end-card/CTA frames that are clear but not useful for notes."""
        try:
            Image.init()
            with Image.open(file_path) as img:
                rgb = img.convert("RGB").resize((160, 90), Image.Resampling.LANCZOS)
                gray = rgb.convert("L")
                hsv = rgb.convert("HSV")
                stats = ImageStat.Stat(gray)
                entropy = gray.entropy()
                edges = gray.filter(ImageFilter.FIND_EDGES)
                edge_pixels = sum(1 for value in edges.getdata() if value > 28)
                edge_ratio = edge_pixels / max(1, gray.width * gray.height)
                saturation_data = list(hsv.getchannel("S").getdata())
                value_data = list(hsv.getchannel("V").getdata())
                center = rgb.crop((
                    int(rgb.width * 0.30),
                    int(rgb.height * 0.33),
                    int(rgb.width * 0.70),
                    int(rgb.height * 0.70),
                ))
                bottom = gray.crop((
                    0,
                    int(gray.height * 0.82),
                    gray.width,
                    gray.height,
                ))
        except Exception:
            return 0.0

        pixel_count = max(1, len(value_data))
        colorful_ratio = sum(
            1 for sat, val in zip(saturation_data, value_data)
            if sat > 46 and val > 55
        ) / pixel_count
        very_bright_ratio = sum(1 for val in value_data if val > 235) / pixel_count
        very_dark_ratio = sum(1 for val in value_data if val < 35) / pixel_count
        near_video_end = bool(duration and timestamp >= max(float(duration) * 0.88, float(duration) - 120))
        center_pixels = list(center.getdata())
        center_black_ratio = sum(
            1 for red, green, blue in center_pixels
            if red < 42 and green < 42 and blue < 42
        ) / max(1, len(center_pixels))
        bottom_values = list(bottom.getdata())
        bottom_text_ratio = sum(1 for val in bottom_values if val < 145) / max(1, len(bottom_values))
        sparse_white_card = (
            very_bright_ratio >= 0.82
            and colorful_ratio <= 0.035
            and entropy <= 2.2
            and edge_ratio <= 0.16
            and very_dark_ratio <= 0.18
        )
        end_card_cta = (
            very_bright_ratio >= 0.76
            and colorful_ratio <= 0.06
            and center_black_ratio >= 0.055
            and bottom_text_ratio >= 0.018
            and edge_ratio <= 0.20
        )
        if end_card_cta and near_video_end:
            return 0.78
        if end_card_cta:
            return 0.50
        if sparse_white_card and (near_video_end or entropy <= 1.35):
            return 0.72
        if sparse_white_card:
            return 0.42
        if very_bright_ratio >= 0.90 and colorful_ratio <= 0.02 and entropy <= 1.4:
            return 0.55
        if stats.mean[0] >= 238 and entropy <= 1.1 and edge_ratio <= 0.08:
            return 0.45
        return 0.0

    def review_screenshot_candidates(
        self,
        candidates: List[FrameCandidate],
        gpt: Optional[GPT],
        section_title: str = "",
        section_context: str = "",
    ) -> Optional[FrameCandidate]:
        if not candidates or not gpt or not getattr(gpt, "supports_vision", False):
            return None
        client = getattr(gpt, "client", None)
        model = getattr(gpt, "model", None)
        if client is None or not model:
            return None

        max_candidates = min(
            _env_int("SCREENSHOT_REVIEW_CANDIDATE_LIMIT", 4, 2, 8),
            len(candidates),
        )
        if len(candidates) <= max_candidates:
            review_candidates = sorted(candidates, key=lambda item: item.timestamp)
        else:
            ordered = sorted(candidates, key=lambda item: item.timestamp)
            high_score = sorted(candidates, key=lambda item: item.score, reverse=True)[:4]
            spread = [
                ordered[round(idx * (len(ordered) - 1) / max(1, max_candidates - 1))]
                for idx in range(max_candidates)
            ]
            by_path = {}
            for item in high_score:
                by_path[item.path] = item
            for item in spread:
                if len(by_path) >= max_candidates:
                    break
                by_path[item.path] = item
            review_candidates = sorted(by_path.values(), key=lambda item: item.timestamp)

        prompt = (
            "你是 VideoNote 的截图评审器。请从候选截图中选择最适合插入学习笔记的一张。\n"
            "优先选择与章节正文相关、信息完整、停留稳定后的最终画面；"
            "避免空白页、过渡页、标题页、半成品、重复画面和无关字幕特写。\n"
            "只返回 JSON：{\"selected\":候选序号整数,\"reason\":\"简短中文原因\",\"confidence\":0到1}\n\n"
            f"章节标题：{section_title or '未知'}\n"
            f"章节正文摘要：\n{section_context or '无'}\n\n"
            "候选截图如下："
        )
        content: list[dict] = [{"type": "text", "text": prompt}]
        for idx, candidate in enumerate(review_candidates):
            content.append({
                "type": "text",
                "text": (
                    f"候选 {idx}: 时间 {self.format_seconds(candidate.timestamp)}, "
                    f"启发式分数 {candidate.score:.3f}"
                ),
            })
            try:
                content.append({
                    "type": "image_url",
                    "image_url": {
                        "url": self.image_data_url(candidate.path),
                        "detail": os.getenv("SCREENSHOT_REVIEW_IMAGE_DETAIL", "low"),
                    },
                })
            except Exception as exc:
                logger.warning(f"候选截图编码失败，跳过视觉评审: {exc}")
                return None

        try:
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": content}],
                    temperature=0,
                )
            except Exception as exc:
                raw = str(exc).lower()
                if "temperature" not in raw or (
                    "does not support" not in raw
                    and "unsupported_value" not in raw
                    and "only the default" not in raw
                ):
                    raise
                response = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": content}],
                )
        except Exception as exc:
            logger.warning(f"多模态截图评审失败，未使用评审结果: {exc}")
            return None

        raw = response.choices[0].message.content
        data = self.extract_json_object(raw)
        if not isinstance(data, dict):
            logger.warning(f"多模态截图评审返回非 JSON，未使用评审结果: {raw}")
            return None

        try:
            selected_idx = int(data.get("selected"))
        except Exception:
            return None
        try:
            confidence_value = float(data.get("confidence", 0))
        except Exception:
            confidence_value = 0
        if selected_idx < 0 or selected_idx >= len(review_candidates):
            return None
        if confidence_value < float(os.getenv("SCREENSHOT_REVIEW_MIN_CONFIDENCE", "0.35")):
            return None
        chosen = review_candidates[selected_idx]
        logger.info(
            "多模态截图评审选择: ts=%s score=%.3f reason=%s confidence=%.2f",
            chosen.timestamp,
            chosen.score,
            data.get("reason", ""),
            confidence_value,
        )
        return chosen

    @staticmethod
    def needs_balanced_review(
        segments,
        heuristic_best: FrameCandidate,
        section_title: str = "",
        section_context: str = "",
    ) -> bool:
        if not segments:
            return False
        text = f"{section_title}\n{section_context}"
        value_score, _reasons = VisualScreenshotAgent.visual_keyword_score(text)
        important_section = value_score >= 3.2 or any(
            keyword in text
            for keyword in ["最终结果", "执行计划", "架构", "流程", "工作流", "结果", "Plan", "Execute", "Agent"]
        )
        if important_section and len(segments) >= 2:
            return True

        ranked = sorted(
            [segment.representative for segment in segments],
            key=lambda item: item.score,
            reverse=True,
        )
        if len(ranked) < 2:
            return False
        score_gap = ranked[0].score - ranked[1].score
        best_is_not_raw_top = ranked[0].path != heuristic_best.path
        ambiguous = score_gap <= float(os.getenv("SCREENSHOT_BALANCED_REVIEW_SCORE_GAP", "0.12"))
        return ambiguous or best_is_not_raw_top

    def can_use_vision_review(self, review_mode: str, gpt: Optional[GPT]) -> bool:
        if review_mode == "off":
            return False
        if not (
            gpt
            and getattr(gpt, "supports_vision", False)
            and getattr(gpt, "client", None)
            and getattr(gpt, "model", None)
        ):
            return False
        if review_mode == "balanced":
            limit = _env_int("SCREENSHOT_VISION_REVIEW_LIMIT", 3, 0, 20)
            with self._vision_review_lock:
                return self._vision_review_count < limit
        return True

    def reserve_vision_review(self, review_mode: str, gpt: Optional[GPT]) -> bool:
        if review_mode == "off":
            return False
        if not (
            gpt
            and getattr(gpt, "supports_vision", False)
            and getattr(gpt, "client", None)
            and getattr(gpt, "model", None)
        ):
            return False
        if review_mode == "balanced":
            limit = _env_int("SCREENSHOT_VISION_REVIEW_LIMIT", 3, 0, 20)
            with self._vision_review_lock:
                if self._vision_review_count >= limit:
                    return False
                self._vision_review_count += 1
                return True
        return True

    @staticmethod
    def suggested_screenshot_count(
        score: float,
        screenshot_times: List[int],
        code_block_count: int,
        subsection_count: int,
        step_count: int,
    ) -> int:
        visual_density = len(screenshot_times) + code_block_count + subsection_count + max(0, step_count // 3)
        target_count = min(4, max(1, len(screenshot_times)))
        if score >= 5.0 and (len(screenshot_times) >= 3 or code_block_count >= 1 or subsection_count >= 2):
            target_count = 2
        if score >= 6.0 and visual_density >= 4:
            target_count = max(target_count, 2)
        if score >= 8.0 and (
            len(screenshot_times) >= 6
            or code_block_count >= 2
            or subsection_count >= 2
            or step_count >= 6
        ):
            target_count = 3
        if score >= 12.0 and (
            len(screenshot_times) >= 10
            or code_block_count >= 3
            or subsection_count >= 3
            or step_count >= 10
        ):
            target_count = 4
        return min(4, max(target_count, min(len(screenshot_times), 4)))

    def analyze_markdown_sections(
        self,
        markdown: str,
        duration: Optional[float],
        transcript_segments: Optional[List[Any]] = None,
    ) -> List[VisualSectionAnalysis]:
        lines = markdown.splitlines()
        markers = self.content_line_markers(markdown)
        if not markers:
            markers = self.heading_line_markers_from_screenshots(markdown)
        transcript_windows = self.transcript_segments_to_windows(transcript_segments)
        if not markers and transcript_windows:
            markers = self.infer_section_markers_from_headings(markdown, duration, transcript_windows)
        if not markers:
            logger.info("No usable timestamp markers or transcript alignment; skip document-driven screenshot planning")
            return []

        analyses: List[VisualSectionAnalysis] = []
        total_duration = int(duration or 0)
        for idx, (line_index, start) in enumerate(markers):
            next_line = markers[idx + 1][0] if idx + 1 < len(markers) else len(lines)
            next_time = markers[idx + 1][1] if idx + 1 < len(markers) else total_duration
            if next_time <= start:
                next_time = start + 60

            title = self.clean_heading_title(lines[line_index] if line_index < len(lines) else "")
            body = "\n".join(lines[line_index:next_line])
            aligned_start, aligned_end, aligned_context, alignment_score = self.align_section_to_transcript(
                title,
                body,
                transcript_windows,
                start,
                next_time,
            )
            if alignment_score >= 0.18:
                start = aligned_start
                next_time = aligned_end
            score, reasons = self.visual_keyword_score(f"{title}\n{body}")

            if re.search(r"```|`[^`]+`", body):
                score += 1.3
                reasons.append("code-block")
            if title and any(word in title for word in ["目录", "总结", "AI总结", "参考", "结论"]):
                score -= 2.0
            if alignment_score >= 0.18:
                score += min(1.2, alignment_score * 2.0)
                reasons.append("transcript-align")

            if score < 2.0:
                continue

            screenshot_times = [ts for _marker, ts in extract_screenshot_timestamps(body)]
            code_block_count = max(0, body.count("```") // 2)
            subsection_count = len(re.findall(r"^#{3,6}\s+", body, flags=re.MULTILINE))
            step_count = len(re.findall(r"^\s*(?:[-*+]|\d+[.)])\s+", body, flags=re.MULTILINE))
            suggested_count = self.suggested_screenshot_count(
                score,
                screenshot_times,
                code_block_count,
                subsection_count,
                step_count,
            )
            insert_lines = self.choose_section_insert_lines(lines, line_index, next_line, suggested_count)
            analyses.append(VisualSectionAnalysis(
                title=title,
                line_index=line_index,
                start=start,
                end=next_time,
                score=score,
                reasons=reasons[:6],
                screenshot_times=screenshot_times,
                suggested_count=suggested_count,
                body=(body + ("\n\n相关字幕：\n" + aligned_context if aligned_context else "")),
                insert_lines=insert_lines,
            ))
        return analyses

    @classmethod
    def infer_section_markers_from_headings(
        cls,
        markdown: str,
        duration: Optional[float],
        transcript_windows: List[Tuple[int, int, str]],
    ) -> List[Tuple[int, int]]:
        lines = markdown.splitlines()
        heading_lines = [
            idx for idx, line in enumerate(lines)
            if re.match(r"^#{1,6}\s+", line)
            and "目录" not in line
            and "AI总结" not in line
        ]
        markers: List[Tuple[int, int]] = []
        for pos, line_idx in enumerate(heading_lines):
            next_heading = heading_lines[pos + 1] if pos + 1 < len(heading_lines) else len(lines)
            title = cls.clean_heading_title(lines[line_idx])
            body = "\n".join(lines[line_idx:next_heading])
            fallback_start = int((duration or 0) * pos / max(1, len(heading_lines))) if duration else 0
            fallback_end = int((duration or 0) * (pos + 1) / max(1, len(heading_lines))) if duration else fallback_start + 60
            start, _end, _context, score = cls.align_section_to_transcript(
                title,
                body,
                transcript_windows,
                fallback_start,
                fallback_end,
            )
            if score >= 0.18:
                markers.append((line_idx, start))
        return sorted(markers, key=lambda item: (item[1], item[0]))

    def plan_visual_screenshots(
        self,
        markdown: str,
        duration: Optional[float],
        transcript_segments: Optional[List[Any]] = None,
    ) -> List[VisualSectionPlan]:
        analyses = self.analyze_markdown_sections(markdown, duration, transcript_segments)
        if not analyses:
            return []

        plans: List[VisualSectionPlan] = []
        total_duration = int(duration or 0)
        for analysis in analyses:
            section_anchor_times = self.section_anchor_times(
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
                anchor_times = self.spread_anchor_times(
                    anchor_source,
                    analysis.suggested_count,
                    min_gap=self.adaptive_min_gap(
                        analysis.start,
                        analysis.end,
                        analysis.suggested_count,
                        len(analysis.screenshot_times),
                    ),
                )
            else:
                anchor_times = section_anchor_times

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
                plans.append(VisualSectionPlan(
                    title=analysis.title,
                    start=ts,
                    end=plan_end,
                    score=analysis.score,
                    reasons=analysis.reasons,
                    line_index=analysis.line_index,
                    context=analysis.body[:1800],
                    insert_line=insert_line,
                    insert_reason="document-section",
                ))

        filtered: List[VisualSectionPlan] = []
        plan_limit = screenshot_content_budget(analyses)
        analysis_by_line = {analysis.line_index: analysis for analysis in analyses}
        for plan in sorted(plans, key=lambda item: (-item.score, item.start)):
            analysis = analysis_by_line.get(plan.line_index)
            min_gap = (
                self.adaptive_min_gap(
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

    def best_screenshot_near_timestamp(
        self,
        video_path: Path,
        timestamp: int,
        duration: Optional[float],
        index: int,
        visual_reader: VideoReader,
        search_end: Optional[int] = None,
        gpt: Optional[GPT] = None,
        section_title: str = "",
        section_context: str = "",
        generated_image_paths: Optional[List[str]] = None,
    ) -> Optional[FrameCandidate]:
        total_duration = int(duration or 0)
        max_candidates = _env_int("SCREENSHOT_CANDIDATE_LIMIT", 10, 5, 16)
        offsets = [0, 6, 12, 18, 26, 34, 45, 60]
        if search_end and search_end > timestamp:
            span = search_end - timestamp
            sampled_span = min(span, 150)
            offsets.extend([
                max(0, int(sampled_span * ratio))
                for ratio in (0.45, 0.65, 0.82, 0.94)
            ])
            offsets.append(max(0, min(span - 2, sampled_span)))
        else:
            remaining = max(0, total_duration - timestamp - 1) if total_duration else 90
            sampled_span = min(remaining, 120)
            offsets.extend([
                max(0, int(sampled_span * ratio))
                for ratio in (0.5, 0.72, 0.9)
            ])
        candidates: List[FrameCandidate] = []
        seen_ts = set()
        for offset_idx, offset in enumerate(self.select_candidate_offsets(offsets, max_candidates)):
            ts = timestamp + offset
            if total_duration:
                ts = max(1, min(total_duration - 1, ts))
            else:
                ts = max(1, ts)
            if ts in seen_ts:
                continue
            seen_ts.add(ts)
            img_path = self.screenshot_func(str(video_path), str(self.image_output_dir), ts, index * 10 + offset_idx)
            if not Path(img_path).exists():
                continue
            if generated_image_paths is not None:
                generated_image_paths.append(img_path)
            exact_hash = visual_reader._calculate_file_md5(img_path)
            score, perceptual_hash = visual_reader._score_frame(img_path)
            penalty = self.non_note_frame_penalty(img_path, ts, duration)
            if penalty:
                score = max(0.0, score - penalty)
            candidates.append(FrameCandidate(
                path=img_path,
                timestamp=ts,
                score=score,
                exact_hash=exact_hash,
                perceptual_hash=perceptual_hash,
            ))

        if not candidates:
            raise RuntimeError(f"未生成可用截图候选: {timestamp}")

        build_segments = getattr(visual_reader, "_build_visual_segments", None)
        if build_segments:
            segments = build_segments(candidates)
        else:
            segments = [
                type("_SingleFrameSegment", (), {
                    "start": candidate.timestamp,
                    "end": candidate.timestamp,
                    "representative": candidate,
                    "frames": [candidate],
                    "duration": 0,
                })()
                for candidate in candidates
            ]
        if not segments:
            raise RuntimeError(f"未生成可用视觉分段: {timestamp}")

        first_ts = min(segment.start for segment in segments)
        last_ts = max(segment.end for segment in segments)
        best_raw_score = max(segment.representative.score for segment in segments)

        def selection_score(segment) -> float:
            candidate = segment.representative
            later_ratio = 0.0 if last_ts <= first_ts else (segment.end - first_ts) / (last_ts - first_ts)
            stable_bonus = min(len(segment.frames) - 1, 5) * 0.08 + min(segment.duration / 24, 1) * 0.16
            singleton_penalty = 0.24 if len(segment.frames) == 1 and len(segments) > 1 else 0.0
            early_penalty = 0.16 if later_ratio < 0.2 and len(segments) > 1 else 0.0
            completeness_bonus = 0.0
            if candidate.score >= max(0.34, best_raw_score - 0.30):
                completeness_bonus += later_ratio * 0.38
                if len(segment.frames) > 1 and later_ratio >= 0.45:
                    completeness_bonus += 0.18
                if later_ratio >= 0.72:
                    completeness_bonus += 0.10
            raw_score_gap_penalty = max(0.0, best_raw_score - candidate.score - 0.26) * 0.65
            return (
                candidate.score
                + stable_bonus
                + completeness_bonus
                - singleton_penalty
                - early_penalty
                - raw_score_gap_penalty
            )

        heuristic_best = max(segments, key=selection_score).representative
        review_mode = screenshot_review_mode()
        has_vision_reviewer = False
        reviewed_best = None
        should_review = review_mode in {"assist", "strict"} or (
            review_mode == "balanced"
            and self.needs_balanced_review(
                segments,
                heuristic_best,
                section_title=section_title,
                section_context=section_context,
            )
        )
        if should_review:
            has_vision_reviewer = self.reserve_vision_review(review_mode, gpt)
            if has_vision_reviewer:
                reviewed_best = self.review_screenshot_candidates(
                    candidates,
                    gpt,
                    section_title=section_title,
                    section_context=section_context,
                )
        if review_mode == "strict" and not has_vision_reviewer:
            raise RuntimeError("多模态截图评审不可用")
        if review_mode == "strict" and has_vision_reviewer and reviewed_best is None:
            raise RuntimeError("多模态截图评审未返回可用结果")
        best = reviewed_best or heuristic_best
        for candidate in candidates:
            if candidate.path != best.path:
                Path(candidate.path).unlink(missing_ok=True)
        if best.score < 0.34:
            Path(best.path).unlink(missing_ok=True)
            raise RuntimeError(f"截图候选质量过低: {best.score:.3f}")
        return best

    @staticmethod
    def fallback_sampling_interval(duration: Optional[float]) -> int:
        if not duration or duration <= 0:
            return 8
        max_sample_windows = 360
        adaptive_interval = max(1, int((duration + max_sample_windows - 1) // max_sample_windows))
        if duration <= 10 * 60:
            return max(6, adaptive_interval)
        if duration <= 30 * 60:
            return max(10, adaptive_interval)
        if duration <= 60 * 60:
            return max(15, adaptive_interval)
        return max(20, adaptive_interval)

    def fallback_screenshot_timestamps(self, video_path: Path, duration: Optional[float]) -> List[int]:
        try:
            with tempfile.TemporaryDirectory(prefix="bilinote_visual_") as tmp_dir:
                tmp_path = Path(tmp_dir)
                reader = self.video_reader_cls(
                    video_path=str(video_path),
                    frame_interval=self.fallback_sampling_interval(duration),
                    frame_dir=str(tmp_path / "frames"),
                    grid_dir=str(tmp_path / "grids"),
                )
                timestamps = reader.extract_representative_timestamps()
                if timestamps:
                    return timestamps
                raise RuntimeError("视觉扫描未返回可用截图时间点")
        except Exception as exc:
            logger.exception("视觉截图时间点提取失败")
            raise RuntimeError("视觉截图时间点提取失败") from exc

    @staticmethod
    def extract_screenshot_timestamps(markdown: str) -> List[Tuple[str, int]]:
        return extract_screenshot_timestamps(markdown)
