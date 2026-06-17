import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Optional, Union

from app.enmus.task_status_enums import TaskStatus

logger = logging.getLogger(__name__)


def write_status_record(
    task_id: Optional[str],
    status: Union[str, TaskStatus],
    message: Optional[str] = None,
    generation_token: Optional[str] = None,
    output_dir: Optional[Path] = None,
    force: bool = False,
) -> None:
    if not task_id:
        return

    note_output_dir = output_dir or Path(os.getenv("NOTE_OUTPUT_DIR", "note_results"))
    note_output_dir.mkdir(parents=True, exist_ok=True)
    status_file = note_output_dir / f"{task_id}.status.json"

    if generation_token and status_file.exists() and not force:
        try:
            existing = json.loads(status_file.read_text(encoding="utf-8"))
            existing_token = existing.get("generation_token")
            if existing_token and existing_token != generation_token:
                logger.info("Skip stale status update (task_id=%s)", task_id)
                return
        except Exception as exc:
            logger.debug("Ignore unreadable status file while updating task status: %s", exc)

    data = {"status": status.value if isinstance(status, TaskStatus) else status}
    if generation_token:
        data["generation_token"] = generation_token
    if message:
        data["message"] = message

    try:
        temp_handle = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            delete=False,
            dir=str(note_output_dir),
            prefix=f"{status_file.name}.",
            suffix=".tmp",
        )
        temp_file = Path(temp_handle.name)

        with temp_handle as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())

        temp_file.replace(status_file)
    except Exception as exc:
        logger.error("Failed to write status file (task_id=%s): %s", task_id, exc)
        try:
            with status_file.open("w", encoding="utf-8") as f:
                f.write(f"Error writing status: {str(exc)}")
        except Exception as fallback_exc:
            logger.error("Failed to write status fallback: %s", fallback_exc)
