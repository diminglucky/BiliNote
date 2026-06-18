import argparse
import json
import re
import time
from dataclasses import asdict, dataclass, field
from hashlib import md5
from pathlib import Path
from typing import Any, Iterable, Optional

from PIL import Image, ImageFilter, ImageStat


IMAGE_PATTERN = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")
SCREENSHOT_MARKER_PATTERN = re.compile(r"\*?Screenshots?-\[[^\]]+\]\*?", re.IGNORECASE)
CONTENT_MARKER_PATTERN = re.compile(r"Content-\[(?:(\d{2}):)?(\d{2}):(\d{2})\]")


@dataclass
class ImageQualityReport:
    url: str
    path: Optional[str]
    exists: bool
    line_index: int
    section: str
    width: int = 0
    height: int = 0
    score: float = 0.0
    entropy: float = 0.0
    contrast: float = 0.0
    edge_ratio: float = 0.0
    sharpness: float = 0.0
    exact_hash: Optional[str] = None
    perceptual_hash: Optional[int] = None
    issues: list[str] = field(default_factory=list)


@dataclass
class StageTiming:
    status: str
    first_seen: float
    last_seen: float
    elapsed_seconds: float
    message: str = ""


@dataclass
class NoteQualityReport:
    task_id: str
    status: str
    generation_token: Optional[str]
    duration_seconds: Optional[float]
    markdown_chars: int
    transcript_segments: int
    image_count: int
    unresolved_marker_count: int
    duplicate_image_pairs: int
    missing_image_count: int
    low_quality_image_count: int
    inserted_sections: list[str]
    stage_timings: list[StageTiming]
    images: list[ImageQualityReport]
    issues: list[str]
    generated_at: float = field(default_factory=time.time)

    @property
    def pass_quality_gate(self) -> bool:
        return not self.issues


def load_task_report(
    task_id: str,
    note_output_dir: str | Path,
    static_dir: str | Path,
) -> NoteQualityReport:
    note_dir = Path(note_output_dir)
    result_path = note_dir / f"{task_id}.json"
    status_path = note_dir / f"{task_id}.status.json"
    if not result_path.exists():
        raise FileNotFoundError(f"Task result not found: {result_path}")

    payload = _load_json(result_path)
    status_payload = _load_json(status_path) if status_path.exists() else {}
    markdown = str(payload.get("markdown") or "")
    audio_meta = payload.get("audio_meta") or {}
    transcript = payload.get("transcript") or {}
    transcript_segments = transcript.get("segments") or []
    if not isinstance(transcript_segments, list):
        transcript_segments = []

    images = analyze_markdown_images(markdown, static_dir)
    issues = collect_note_issues(markdown, images)
    stage_timings = summarize_stage_timings(status_payload.get("history") or [])
    duplicate_pairs = count_duplicate_pairs(images)
    missing_count = sum(1 for item in images if not item.exists)
    low_quality_count = sum(1 for item in images if "low-quality" in item.issues)
    unresolved_markers = len(SCREENSHOT_MARKER_PATTERN.findall(markdown))
    inserted_sections = sorted({item.section for item in images if item.section})

    if unresolved_markers:
        issues.append(f"unresolved-screenshot-markers:{unresolved_markers}")
    if duplicate_pairs:
        issues.append(f"duplicate-images:{duplicate_pairs}")
    if missing_count:
        issues.append(f"missing-images:{missing_count}")
    if low_quality_count:
        issues.append(f"low-quality-images:{low_quality_count}")
    if images and not inserted_sections:
        issues.append("images-without-section-context")
    if payload.get("enhance_token") and status_payload.get("status") == "SUCCESS" and not images:
        issues.append("screenshot-enhancement-finished-without-images")

    return NoteQualityReport(
        task_id=task_id,
        status=str(status_payload.get("status") or "UNKNOWN"),
        generation_token=payload.get("generation_token") or status_payload.get("generation_token"),
        duration_seconds=_safe_float(audio_meta.get("duration")),
        markdown_chars=len(markdown),
        transcript_segments=len(transcript_segments),
        image_count=len(images),
        unresolved_marker_count=unresolved_markers,
        duplicate_image_pairs=duplicate_pairs,
        missing_image_count=missing_count,
        low_quality_image_count=low_quality_count,
        inserted_sections=inserted_sections,
        stage_timings=stage_timings,
        images=images,
        issues=issues,
    )


def analyze_markdown_images(markdown: str, static_dir: str | Path) -> list[ImageQualityReport]:
    lines = markdown.splitlines()
    reports: list[ImageQualityReport] = []
    for line_index, line in enumerate(lines):
        for match in IMAGE_PATTERN.finditer(line):
            url = match.group(1).strip()
            section = nearest_heading(lines, line_index)
            image_path = resolve_image_path(url, static_dir)
            report = inspect_image(url, image_path, line_index, section)
            if not has_useful_text_context(lines, line_index):
                report.issues.append("thin-markdown-context")
            reports.append(report)
    mark_duplicate_images(reports)
    return reports


def inspect_image(
    url: str,
    path: Optional[Path],
    line_index: int,
    section: str,
) -> ImageQualityReport:
    if path is None:
        return ImageQualityReport(
            url=url,
            path=None,
            exists=False,
            line_index=line_index,
            section=section,
            issues=["external-image-not-audited"],
        )
    if not path.exists():
        return ImageQualityReport(
            url=url,
            path=str(path),
            exists=False,
            line_index=line_index,
            section=section,
            issues=["missing-image"],
        )

    report = ImageQualityReport(
        url=url,
        path=str(path),
        exists=True,
        line_index=line_index,
        section=section,
    )
    try:
        with path.open("rb") as f:
            report.exact_hash = md5(f.read()).hexdigest()
        with Image.open(path) as img:
            report.width, report.height = img.size
            score, entropy, contrast, edge_ratio, sharpness, perceptual_hash = score_image(img)
            report.score = round(score, 4)
            report.entropy = round(entropy, 4)
            report.contrast = round(contrast, 4)
            report.edge_ratio = round(edge_ratio, 4)
            report.sharpness = round(sharpness, 4)
            report.perceptual_hash = perceptual_hash
    except Exception as exc:
        report.issues.append(f"image-read-error:{exc}")
        return report

    if report.width < 960 or report.height < 540:
        report.issues.append("low-resolution")
    if report.score < 0.38:
        report.issues.append("low-quality")
    if report.sharpness < 0.12 and report.edge_ratio < 0.05:
        report.issues.append("blurry-or-blank")
    return report


def score_image(img: Image.Image) -> tuple[float, float, float, float, float, int]:
    native_gray = img.convert("L")
    rgb = img.convert("RGB").resize((160, 90), Image.Resampling.LANCZOS)
    gray = rgb.convert("L")
    hsv = rgb.convert("HSV")
    stats = ImageStat.Stat(gray)
    brightness = stats.mean[0]
    contrast = stats.stddev[0]
    entropy = gray.entropy()
    edges = gray.filter(ImageFilter.FIND_EDGES)
    edge_values = list(edges.getdata())
    edge_strength = ImageStat.Stat(edges).mean[0]
    edge_ratio = sum(1 for value in edge_values if value > 28) / max(1, len(edge_values))
    native_edges = native_gray.filter(ImageFilter.FIND_EDGES)
    native_edge_values = list(native_edges.getdata())
    sharp_edge_ratio = sum(1 for value in native_edge_values if value > 36) / max(1, len(native_edge_values))
    sharp_edge_strength = ImageStat.Stat(native_edges).mean[0]
    saturation = list(hsv.getchannel("S").getdata())
    value = list(hsv.getchannel("V").getdata())
    pixel_count = max(1, len(value))
    colorful_ratio = sum(1 for sat, val in zip(saturation, value) if sat > 46 and val > 55) / pixel_count
    bright_foreground_ratio = sum(1 for sat, val in zip(saturation, value) if sat < 90 and val > 185) / pixel_count
    dark_foreground_ratio = sum(1 for val in value if val < 45) / pixel_count
    perceptual_hash = _perceptual_hash(gray)

    brightness_score = 1 - min(abs(brightness - 120) / 120, 1)
    contrast_score = min(contrast / 50, 1)
    entropy_score = min(entropy / 6, 1)
    edge_score = min(edge_strength / 18, 1)
    edge_coverage_score = min(edge_ratio / 0.18, 1)
    sharpness_score = min((sharp_edge_strength / 22) * 0.55 + (sharp_edge_ratio / 0.10) * 0.45, 1)
    foreground_signal = colorful_ratio + bright_foreground_ratio + min(dark_foreground_ratio, 0.25)
    foreground_score = min(foreground_signal / 0.18, 1)
    color_score = min(colorful_ratio / 0.18, 1)
    score = (
        brightness_score * 0.05
        + contrast_score * 0.12
        + entropy_score * 0.14
        + edge_score * 0.10
        + edge_coverage_score * 0.11
        + sharpness_score * 0.16
        + foreground_score * 0.25
        + color_score * 0.07
    )
    if foreground_signal < 0.08:
        score *= foreground_signal / 0.08
    if contrast < 10 and colorful_ratio < 0.03:
        score *= 0.25
    if edge_ratio < 0.025 and foreground_signal < 0.12:
        score *= 0.55
    if sharp_edge_strength < 5 and sharp_edge_ratio < 0.018:
        score *= 0.45
    return score, entropy, contrast, edge_ratio, sharpness_score, perceptual_hash


def summarize_stage_timings(history: Iterable[Any]) -> list[StageTiming]:
    events = []
    for item in history:
        if not isinstance(item, dict):
            continue
        status = str(item.get("status") or "")
        timestamp = _safe_float(item.get("timestamp"))
        if not status or timestamp is None:
            continue
        events.append((status, timestamp, str(item.get("message") or "")))
    if not events:
        return []

    stage_map: dict[str, dict[str, Any]] = {}
    for status, timestamp, message in events:
        current = stage_map.setdefault(
            status,
            {"first": timestamp, "last": timestamp, "message": message},
        )
        current["first"] = min(current["first"], timestamp)
        current["last"] = max(current["last"], timestamp)
        if message:
            current["message"] = message

    ordered = []
    for status, values in sorted(stage_map.items(), key=lambda item: item[1]["first"]):
        ordered.append(StageTiming(
            status=status,
            first_seen=values["first"],
            last_seen=values["last"],
            elapsed_seconds=max(0.0, values["last"] - values["first"]),
            message=values.get("message") or "",
        ))
    return ordered


def collect_note_issues(markdown: str, images: list[ImageQualityReport]) -> list[str]:
    issues: list[str] = []
    if len(markdown.strip()) < 500:
        issues.append("markdown-too-short")
    if "##" not in markdown:
        issues.append("missing-headings")
    if "AI" not in markdown and "总结" not in markdown and "Summary" not in markdown:
        issues.append("missing-summary-signal")
    if not images and SCREENSHOT_MARKER_PATTERN.search(markdown):
        issues.append("markers-left-without-rendered-images")
    for image in images:
        for issue in image.issues:
            issues.append(f"image:{Path(image.path or image.url).name}:{issue}")
    return issues


def write_report_files(report: NoteQualityReport, output_dir: str | Path) -> tuple[Path, Path]:
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    json_path = target_dir / f"{report.task_id}.quality.json"
    md_path = target_dir / f"{report.task_id}.quality.md"
    json_path.write_text(
        json.dumps(asdict(report), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md_path.write_text(render_markdown_report(report), encoding="utf-8")
    return json_path, md_path


def render_markdown_report(report: NoteQualityReport) -> str:
    lines = [
        f"# Note Quality Benchmark: {report.task_id}",
        "",
        f"- Status: {report.status}",
        f"- Pass: {'yes' if report.pass_quality_gate else 'no'}",
        f"- Markdown chars: {report.markdown_chars}",
        f"- Transcript segments: {report.transcript_segments}",
        f"- Video duration: {report.duration_seconds or 0:.1f}s",
        f"- Images: {report.image_count}",
        f"- Missing images: {report.missing_image_count}",
        f"- Low quality images: {report.low_quality_image_count}",
        f"- Duplicate image pairs: {report.duplicate_image_pairs}",
        f"- Unresolved screenshot markers: {report.unresolved_marker_count}",
        "",
        "## Issues",
        "",
    ]
    if report.issues:
        lines.extend(f"- {issue}" for issue in report.issues)
    else:
        lines.append("- none")

    lines.extend(["", "## Stage Timings", ""])
    if report.stage_timings:
        lines.append("| Stage | Seen count window | Message |")
        lines.append("| --- | ---: | --- |")
        for item in report.stage_timings:
            lines.append(f"| {item.status} | {item.elapsed_seconds:.2f}s | {item.message} |")
    else:
        lines.append("- no status history available")

    lines.extend(["", "## Images", ""])
    if report.images:
        lines.append("| # | Section | Score | Size | Issues | Path |")
        lines.append("| ---: | --- | ---: | --- | --- | --- |")
        for idx, image in enumerate(report.images, start=1):
            size = f"{image.width}x{image.height}" if image.exists else "missing"
            issues = ", ".join(image.issues) if image.issues else "none"
            lines.append(
                f"| {idx} | {image.section or '-'} | {image.score:.3f} | {size} | {issues} | {image.path or image.url} |"
            )
    else:
        lines.append("- no markdown images")
    lines.append("")
    return "\n".join(lines)


def resolve_image_path(url: str, static_dir: str | Path) -> Optional[Path]:
    if re.match(r"^https?://", url):
        return None
    normalized = url.split("?", 1)[0].split("#", 1)[0].replace("\\", "/")
    if normalized.startswith("/static/"):
        return Path(static_dir) / normalized.removeprefix("/static/")
    if normalized.startswith("static/"):
        return Path(static_dir).parent / normalized
    if normalized.startswith("/"):
        return Path(static_dir).parent / normalized.lstrip("/")
    return Path(static_dir).parent / normalized


def nearest_heading(lines: list[str], line_index: int) -> str:
    for idx in range(line_index, -1, -1):
        line = lines[idx].strip()
        if line.startswith("#"):
            return re.sub(r"^#+\s*", "", line).strip()
    return ""


def has_useful_text_context(lines: list[str], line_index: int) -> bool:
    start = max(0, line_index - 4)
    end = min(len(lines), line_index + 5)
    context = "\n".join(
        line.strip()
        for idx, line in enumerate(lines[start:end], start=start)
        if idx != line_index and line.strip() and not IMAGE_PATTERN.search(line)
    )
    return len(context) >= 30


def mark_duplicate_images(reports: list[ImageQualityReport]) -> None:
    for left_idx, left in enumerate(reports):
        if not left.exists:
            continue
        for right in reports[left_idx + 1:]:
            if not right.exists:
                continue
            if left.exact_hash and left.exact_hash == right.exact_hash:
                left.issues.append("duplicate")
                right.issues.append("duplicate")
                continue
            if (
                left.perceptual_hash is not None
                and right.perceptual_hash is not None
                and _hamming_distance(left.perceptual_hash, right.perceptual_hash) <= 3
            ):
                left.issues.append("near-duplicate")
                right.issues.append("near-duplicate")


def count_duplicate_pairs(reports: list[ImageQualityReport]) -> int:
    count = 0
    for left_idx, left in enumerate(reports):
        if not left.exists:
            continue
        for right in reports[left_idx + 1:]:
            if not right.exists:
                continue
            if left.exact_hash and left.exact_hash == right.exact_hash:
                count += 1
            elif (
                left.perceptual_hash is not None
                and right.perceptual_hash is not None
                and _hamming_distance(left.perceptual_hash, right.perceptual_hash) <= 3
            ):
                count += 1
    return count


def _perceptual_hash(gray: Image.Image) -> int:
    thumb = gray.resize((8, 8), Image.Resampling.LANCZOS)
    pixels = list(thumb.getdata())
    average = sum(pixels) / len(pixels)
    value = 0
    for idx, pixel in enumerate(pixels):
        if pixel >= average:
            value |= 1 << idx
    return value


def _hamming_distance(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    return data if isinstance(data, dict) else {}


def _safe_float(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit generated note quality for a saved task.")
    parser.add_argument("task_id")
    parser.add_argument("--note-output-dir", default="note_results")
    parser.add_argument("--static-dir", default="static")
    parser.add_argument("--report-dir", default="benchmark_reports")
    args = parser.parse_args()

    report = load_task_report(args.task_id, args.note_output_dir, args.static_dir)
    json_path, md_path = write_report_files(report, args.report_dir)
    print(f"quality_pass={str(report.pass_quality_gate).lower()}")
    print(f"json_report={json_path}")
    print(f"markdown_report={md_path}")
    if report.issues:
        print("issues=" + ", ".join(report.issues[:12]))
    return 0 if report.pass_quality_gate else 2


if __name__ == "__main__":
    raise SystemExit(main())
