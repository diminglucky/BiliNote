import base64
import json
import logging
import mimetypes
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Tuple, Type

from app.gpt.base import GPT
from app.utils.screenshot_marker import extract_screenshot_timestamps
from app.utils.video_helper import generate_screenshot
from app.utils.video_reader import FrameCandidate, VideoReader

logger = logging.getLogger(__name__)


@dataclass
class VisualSectionPlan:
    title: str
    start: int
    end: int
    score: float
    reasons: List[str]
    line_index: int


@dataclass
class VisualScreenshotState:
    markdown: str
    video_path: Path
    duration: Optional[float] = None
    gpt: Optional[GPT] = None
    matches: Optional[List[Tuple[str, int]]] = None
    visual_plans: Optional[List[VisualSectionPlan]] = None
    generated_images: Optional[List[Tuple[int, str]]] = None
    diagnostics: Optional[List[str]] = None


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

    def insert_screenshots(
        self,
        markdown: str,
        video_path: Path,
        duration: Optional[float] = None,
        gpt: Optional[GPT] = None,
    ) -> str | None:
        state = self.run(VisualScreenshotState(
            markdown=markdown,
            video_path=video_path,
            duration=duration,
            gpt=gpt,
        ))
        return state.markdown

    def run(self, state: VisualScreenshotState) -> VisualScreenshotState:
        state = self.prepare_state(state)
        state = self.filter_marker_node(state)
        state = self.compose_images_node(state)
        return state

    def prepare_state(self, state: VisualScreenshotState) -> VisualScreenshotState:
        if state.diagnostics is None:
            state.diagnostics = []
        state.matches = extract_screenshot_timestamps(state.markdown)
        state.visual_plans = self.plan_visual_screenshots(state.markdown, state.duration)
        state.generated_images = []
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
        matches = state.matches or []
        visual_plans = state.visual_plans or []

        if not matches:
            state.markdown = self.fallback_plan_images_node(state)
            return state

        visual_reader = self.create_visual_reader(state.video_path)
        inserted_visuals: List[FrameCandidate] = []
        generated_images = self.marker_images_node(state, visual_reader, inserted_visuals)
        if state.generated_images is not None:
            state.generated_images.extend(generated_images)

        fallback_images = self.supplement_missing_plan_images_node(
            state,
            visual_reader,
            inserted_visuals,
            generated_images,
            start_index=len(matches),
        )
        if fallback_images:
            if state.generated_images is not None:
                state.generated_images.extend(fallback_images)
            state.markdown = self.insert_fallback_images_near_sections(state.markdown, fallback_images)
        return state

    def create_visual_reader(self, video_path: Path) -> VideoReader:
        return self.video_reader_cls(
            video_path=str(video_path),
            frame_dir=str(self.image_output_dir),
            grid_dir=str(self.image_output_dir),
        )

    def fallback_plan_images_node(self, state: VisualScreenshotState) -> str:
        visual_plans = state.visual_plans or []
        if not visual_plans:
            return state.markdown
        fallback_images: List[Tuple[int, str]] = []
        visual_reader = self.create_visual_reader(state.video_path)
        inserted_visuals: List[FrameCandidate] = []
        for idx, plan in enumerate(visual_plans):
            try:
                candidate = self.best_screenshot_near_timestamp(
                    video_path=state.video_path,
                    timestamp=plan.start,
                    duration=state.duration,
                    index=idx,
                    visual_reader=visual_reader,
                    search_end=plan.end,
                    gpt=state.gpt,
                    section_title=plan.title,
                    section_context=self.section_context_for_plan(state.markdown, plan),
                )
                if candidate is None:
                    continue
                if any(visual_reader._is_same_visual_state(prev, candidate) for prev in inserted_visuals):
                    Path(candidate.path).unlink(missing_ok=True)
                    continue
                inserted_visuals.append(candidate)
                fallback_images.append((plan.start, f"![]({self.image_url(candidate.path)})"))
            except Exception as exc:
                self.add_diagnostic(state, f"fallback_failed:{plan.start}:{exc}")
                logger.error(f"兜底截图失败 (timestamp={plan.start})：{exc}")
        if fallback_images:
            if state.generated_images is not None:
                state.generated_images.extend(fallback_images)
            return self.insert_fallback_images_near_sections(state.markdown, fallback_images)
        return state.markdown

    def marker_images_node(
        self,
        state: VisualScreenshotState,
        visual_reader: VideoReader,
        inserted_visuals: List[FrameCandidate],
    ) -> List[Tuple[int, str]]:
        matches = state.matches or []
        visual_plans = state.visual_plans or []
        generated_images: List[Tuple[int, str]] = []
        for idx, (marker, ts) in enumerate(matches):
            try:
                plan = self.matching_visual_plan(ts, visual_plans)
                candidate = self.best_screenshot_near_timestamp(
                    video_path=state.video_path,
                    timestamp=ts,
                    duration=state.duration,
                    index=idx,
                    visual_reader=visual_reader,
                    search_end=plan.end if plan else None,
                    gpt=state.gpt,
                    section_title=plan.title if plan else "",
                    section_context=self.section_context_for_plan(state.markdown, plan) if plan else "",
                )
                if candidate is None:
                    state.markdown = state.markdown.replace(marker, "", 1)
                    continue
                if not Path(candidate.path).exists():
                    logger.error(f"生成截图失败 (timestamp={ts})：文件未生成")
                    continue
                if any(visual_reader._is_same_visual_state(prev, candidate) for prev in inserted_visuals):
                    Path(candidate.path).unlink(missing_ok=True)
                    state.markdown = state.markdown.replace(marker, "", 1)
                    continue
                inserted_visuals.append(candidate)
                img_url = self.image_url(candidate.path)
                state.markdown = state.markdown.replace(marker, f"![]({img_url})", 1)
                generated_images.append((candidate.timestamp, f"![]({img_url})"))
            except Exception as exc:
                self.add_diagnostic(state, f"marker_failed:{ts}:{exc}")
                logger.error(f"生成截图失败 (timestamp={ts})：{exc}")
        return generated_images

    def supplement_missing_plan_images_node(
        self,
        state: VisualScreenshotState,
        visual_reader: VideoReader,
        inserted_visuals: List[FrameCandidate],
        generated_images: List[Tuple[int, str]],
        start_index: int,
    ) -> List[Tuple[int, str]]:
        visual_plans = state.visual_plans or []
        covered_times = {
            plan.start
            for image_ts, _image in generated_images
            for plan in visual_plans
            if max(0, plan.start - 45) <= image_ts <= plan.end + 15
        }
        missing_plans = [plan for plan in visual_plans if plan.start not in covered_times]
        fallback_images: List[Tuple[int, str]] = []
        if missing_plans:
            for offset, plan in enumerate(missing_plans):
                try:
                    candidate = self.best_screenshot_near_timestamp(
                        video_path=state.video_path,
                        timestamp=plan.start,
                        duration=state.duration,
                        index=start_index + offset,
                        visual_reader=visual_reader,
                        search_end=plan.end,
                        gpt=state.gpt,
                        section_title=plan.title,
                        section_context=self.section_context_for_plan(state.markdown, plan),
                    )
                    if candidate is None:
                        continue
                    if any(visual_reader._is_same_visual_state(prev, candidate) for prev in inserted_visuals):
                        Path(candidate.path).unlink(missing_ok=True)
                        continue
                    inserted_visuals.append(candidate)
                    fallback_images.append((candidate.timestamp, f"![]({self.image_url(candidate.path)})"))
                except Exception as exc:
                    self.add_diagnostic(state, f"supplement_failed:{plan.start}:{exc}")
                    logger.error(f"补充截图失败 (timestamp={plan.start})：{exc}")
        return fallback_images

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
        if plan.line_index >= len(lines):
            return plan.title
        end_line = VisualScreenshotAgent.next_heading_line(lines, plan.line_index)
        context = "\n".join(lines[plan.line_index:end_line]).strip()
        return context[:3000]

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

        max_candidates = min(8, len(candidates))
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
            "你是 BiliNote 的截图评审器。请从候选截图中选择最适合插入学习笔记的一张。\n"
            "选择标准按优先级排序：\n"
            "1. 与当前章节标题和正文最相关。\n"
            "2. 信息完整，优先包含最终结果、更新后的计划、运行结果、完整流程图或关键代码。\n"
            "3. 避免空白页、过渡动画、刚开始出现的半成品画面、重复画面、无关字幕特写。\n"
            "4. 如果后面的截图只是更空或已经切到无关内容，不要为了靠后而选择它。\n"
            "只返回 JSON，不要输出解释文字。格式："
            "{\"selected\":候选序号整数,\"reason\":\"简短中文原因\",\"confidence\":0到1}\n\n"
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
                        "detail": "high",
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
            logger.warning(f"多模态截图评审失败，使用启发式结果: {exc}")
            return None

        raw = response.choices[0].message.content
        data = self.extract_json_object(raw)
        if not isinstance(data, dict):
            logger.warning(f"多模态截图评审返回非 JSON，使用启发式结果: {raw}")
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
    def filter_screenshot_matches_by_structure(
        markdown: str,
        matches: List[Tuple[str, int]],
        plans: List[VisualSectionPlan],
    ) -> Tuple[str, List[Tuple[str, int]]]:
        if not plans:
            for marker, _ts in matches:
                markdown = markdown.replace(marker, "", 1)
            return markdown, []

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
    def visual_keyword_score(text: str) -> Tuple[float, List[str]]:
        text = re.sub(r"\*?Screenshot-\[(?:\d{2}:)?\d{2}:\d{2}\]\*?", "", text)
        keyword_groups = [
            (2.2, ["架构图", "流程图", "示意图", "关系图", "拓扑图", "时序图", "脑图", "图表", "表格"]),
            (1.8, ["界面", "页面", "屏幕", "窗口", "控制台", "终端", "IDE", "编辑器", "运行结果"]),
            (1.6, ["代码", "公式", "命令", "配置", "参数", "报错", "日志"]),
            (1.4, ["实操", "演示", "操作", "步骤", "案例", "示例", "实验"]),
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

    def plan_visual_screenshots(
        self,
        markdown: str,
        duration: Optional[float],
    ) -> List[VisualSectionPlan]:
        lines = markdown.splitlines()
        markers = self.content_line_markers(markdown)
        if not markers:
            markers = self.heading_line_markers_from_screenshots(markdown)
        if not markers:
            logger.info("未找到可用时间标记，跳过结构化截图规划")
            return []

        plans: List[VisualSectionPlan] = []
        total_duration = int(duration or 0)
        for idx, (line_index, start) in enumerate(markers):
            next_line = markers[idx + 1][0] if idx + 1 < len(markers) else len(lines)
            next_time = markers[idx + 1][1] if idx + 1 < len(markers) else total_duration
            if next_time <= start:
                next_time = start + 60

            title = self.clean_heading_title(lines[line_index] if line_index < len(lines) else "")
            body = "\n".join(lines[line_index:next_line])
            section_duration = max(0, next_time - start)
            score, reasons = self.visual_keyword_score(f"{title}\n{body}")

            if re.search(r"```|`[^`]+`", body):
                score += 1.3
                reasons.append("code-block")
            if section_duration >= 180 and score >= 1.2:
                score += 0.8
                reasons.append("long-visual-section")
            if title and any(word in title for word in ["目录", "总结", "AI总结", "参考", "结论"]):
                score -= 2.0

            if score >= 2.0:
                screenshot_times = [ts for _marker, ts in extract_screenshot_timestamps(body)]
                code_block_count = max(0, body.count("```") // 2)
                subsection_count = len(re.findall(r"^#{3,6}\s+", body, flags=re.MULTILINE))

                target_count = 1
                if score >= 5.0 and (section_duration >= 150 or len(screenshot_times) >= 3 or code_block_count >= 1):
                    target_count = 2
                if score >= 6.0 and section_duration >= 240 and subsection_count >= 2:
                    target_count = max(target_count, 2)
                if score >= 8.0 and (
                    section_duration >= 360
                    or len(screenshot_times) >= 6
                    or code_block_count >= 2
                    or subsection_count >= 2
                ):
                    target_count = 3
                if score >= 12.0 and (
                    section_duration >= 600
                    or len(screenshot_times) >= 10
                    or code_block_count >= 3
                    or subsection_count >= 3
                ):
                    target_count = 4

                section_anchor_times = self.section_anchor_times(start, next_time, target_count)
                anchor_times = (
                    self.spread_anchor_times(screenshot_times + section_anchor_times, target_count)
                    if screenshot_times
                    else section_anchor_times
                )
                for anchor_idx, anchor_time in enumerate(anchor_times):
                    ts = anchor_time
                    if total_duration:
                        ts = max(1, min(total_duration - 1, ts))
                    plan_end = anchor_times[anchor_idx + 1] if anchor_idx + 1 < len(anchor_times) else next_time
                    if total_duration:
                        plan_end = max(ts + 1, min(total_duration - 1, plan_end))
                    plans.append(VisualSectionPlan(
                        title=title,
                        start=ts,
                        end=plan_end,
                        score=score,
                        reasons=reasons[:6],
                        line_index=line_index,
                    ))

        filtered: List[VisualSectionPlan] = []
        min_gap = 45
        for plan in sorted(plans, key=lambda item: (-item.score, item.start)):
            if any(abs(plan.start - kept.start) < min_gap for kept in filtered):
                continue
            filtered.append(plan)

        filtered.sort(key=lambda item: item.start)
        logger.info(
            "结构化截图规划完成: %s",
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
    ) -> Optional[FrameCandidate]:
        total_duration = int(duration or 0)
        offsets = [0, 4, 8, 14, 22, 34, 50]
        if search_end and search_end > timestamp:
            span = search_end - timestamp
            sampled_span = min(span, 120)
            offsets.extend([
                max(0, int(sampled_span * ratio))
                for ratio in (0.25, 0.5, 0.75)
            ])
            offsets.append(max(0, min(span - 2, sampled_span)))
        else:
            remaining = max(0, total_duration - timestamp - 1) if total_duration else 90
            sampled_span = min(remaining, 90)
            offsets.extend([
                max(0, int(sampled_span * ratio))
                for ratio in (0.65, 0.9)
            ])
        candidates: List[FrameCandidate] = []
        seen_ts = set()
        for offset_idx, offset in enumerate(sorted(set(offsets))):
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
            exact_hash = visual_reader._calculate_file_md5(img_path)
            score, perceptual_hash = visual_reader._score_frame(img_path)
            candidates.append(FrameCandidate(
                path=img_path,
                timestamp=ts,
                score=score,
                exact_hash=exact_hash,
                perceptual_hash=perceptual_hash,
            ))

        if not candidates:
            return None

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
            return None

        first_ts = min(segment.start for segment in segments)
        last_ts = max(segment.end for segment in segments)
        best_raw_score = max(segment.representative.score for segment in segments)

        def selection_score(segment) -> float:
            candidate = segment.representative
            later_ratio = 0.0 if last_ts <= first_ts else (segment.end - first_ts) / (last_ts - first_ts)
            stable_bonus = min(len(segment.frames) - 1, 4) * 0.07 + min(segment.duration / 30, 1) * 0.12
            singleton_penalty = 0.22 if len(segment.frames) == 1 and len(segments) > 1 else 0.0
            completeness_bonus = 0.0
            if candidate.score >= max(0.34, best_raw_score - 0.22):
                completeness_bonus += later_ratio * 0.24
                if len(segment.frames) > 1 and later_ratio >= 0.45:
                    completeness_bonus += 0.12
            return candidate.score + stable_bonus + completeness_bonus - singleton_penalty

        heuristic_best = max(segments, key=selection_score).representative
        reviewed_best = self.review_screenshot_candidates(
            candidates,
            gpt,
            section_title=section_title,
            section_context=section_context,
        )
        best = reviewed_best or heuristic_best
        for candidate in candidates:
            if candidate.path != best.path:
                Path(candidate.path).unlink(missing_ok=True)
        if best.score < 0.34:
            Path(best.path).unlink(missing_ok=True)
            return None
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
        except Exception as exc:
            logger.warning(f"视觉截图兜底失败，改用均匀时间点: {exc}")

        return self.fallback_uniform_timestamps(duration)

    @staticmethod
    def fallback_uniform_timestamps(duration: Optional[float]) -> List[int]:
        if not duration or duration <= 0:
            return [20, 60, 120]
        total = int(duration)
        candidates = [int(total * 0.2), int(total * 0.5), int(total * 0.8)]
        return sorted({max(1, min(total - 1, t)) for t in candidates})

    @staticmethod
    def extract_screenshot_timestamps(markdown: str) -> List[Tuple[str, int]]:
        return extract_screenshot_timestamps(markdown)
