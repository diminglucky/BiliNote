import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Optional, Tuple


logger = logging.getLogger(__name__)

MIN_SCREENSHOT_VIDEO_WIDTH = int(os.getenv("MIN_SCREENSHOT_VIDEO_WIDTH", "1280"))


def probe_video_size(video_path: str | Path) -> Optional[Tuple[int, int]]:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=width,height",
                "-of",
                "csv=s=x:p=0",
                str(video_path),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
    except Exception as exc:
        logger.warning("Unable to inspect video resolution: %s", exc)
        return None

    if result.returncode != 0:
        logger.warning("ffprobe failed while inspecting video: %s", (result.stderr or result.stdout).strip())
        return None

    output = (result.stdout or "").strip()
    if "x" not in output:
        return None

    try:
        width, height = output.split("x", 1)
        return int(width), int(height)
    except ValueError:
        return None


def is_screenshot_ready_video(video_path: str | Path, *, trust_unknown: bool = False) -> bool:
    size = probe_video_size(video_path)
    if size is None:
        return trust_unknown
    width, _height = size
    return width >= MIN_SCREENSHOT_VIDEO_WIDTH


def quarantine_low_quality_video(video_path: str | Path) -> Optional[str]:
    path = Path(video_path)
    if not path.exists():
        return None
    if is_screenshot_ready_video(path):
        return None

    quarantine_path = f"{path}.lowres.{int(time.time())}"
    logger.info("Cached video is not sharp enough for screenshots; refreshing: %s", path)
    os.replace(path, quarantine_path)
    return quarantine_path


def restore_quarantined_video(quarantine_path: Optional[str], video_path: str | Path) -> None:
    if quarantine_path and os.path.exists(quarantine_path):
        os.replace(quarantine_path, video_path)


def cleanup_quarantined_video(quarantine_path: Optional[str]) -> None:
    if quarantine_path and os.path.exists(quarantine_path):
        os.remove(quarantine_path)
