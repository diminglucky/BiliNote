import shutil
from pathlib import Path

from dotenv import load_dotenv
import subprocess
import os
import uuid
load_dotenv()
api_path = os.getenv("API_BASE_URL", "http://localhost")
BACKEND_PORT= os.getenv("BACKEND_PORT", 8483)

BACKEND_BASE_URL = f"{api_path}:{BACKEND_PORT}"

from typing import Optional


def _screenshot_extension() -> str:
    image_format = os.getenv("SCREENSHOT_IMAGE_FORMAT", "png").strip().lower()
    if image_format in {"jpg", "jpeg"}:
        return "jpg"
    return "png"


def generate_screenshot(video_path: str, output_dir: str, timestamp: int, index: int) -> str:
    """
    ?? ffmpeg ?????????????
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    extension = _screenshot_extension()
    filename = f"screenshot_{index:03}_{uuid.uuid4()}.{extension}"
    output_path = output_dir / filename

    command = [
        "ffmpeg",
        "-ss", str(timestamp),
        "-i", str(video_path),
        "-frames:v", "1",
        "-y",
    ]
    if extension == "jpg":
        command.extend(["-q:v", os.getenv("SCREENSHOT_JPEG_QUALITY", "1")])
    command.extend([str(output_path)])

    print("Running command:", command)
    result = subprocess.run(command, capture_output=True, text=True)

    if result.returncode != 0:
        print("ffmpeg failed:", result.stderr)

    return str(output_path)



def save_cover_to_static(local_cover_path: str, subfolder: Optional[str] = "cover") -> str:
    """
    ???????? static ???????????????
    :param local_cover_path: ??????????????? jpg?
    :param subfolder: ??????? cover??????
    :return: ????????? /static/cover/xxx.jpg
    """
    # ?????
    project_root = os.getcwd()

    # static目录
    static_dir = os.path.join(project_root, "static")

    # ???????
    target_dir = os.path.join(static_dir, subfolder or "cover")
    os.makedirs(target_dir, exist_ok=True)

    # 拷贝文件
    file_name = os.path.basename(local_cover_path)
    target_path = os.path.join(target_dir, file_name)
    shutil.copy2(local_cover_path, target_path)  # ?????????
    image_relative_path = f"/static/{subfolder}/{file_name}".replace("\\", "/")
    url_path = f"{BACKEND_BASE_URL.rstrip('/')}/{image_relative_path.lstrip('/')}"
    # 返回前端可访问的路径
    return url_path
