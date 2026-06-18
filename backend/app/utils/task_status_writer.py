import json
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any, Optional, Union

from app.enmus.task_status_enums import TaskStatus

logger = logging.getLogger(__name__)


def _status_value(status: Union[str, TaskStatus]) -> str:
    return status.value if isinstance(status, TaskStatus) else str(status)


def _load_existing_status(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


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

    existing = _load_existing_status(status_file) if status_file.exists() else {}
    if generation_token and existing and not force:
        existing_token = existing.get("generation_token")
        if existing_token and existing_token != generation_token:
            logger.info("Skip stale status update (task_id=%s)", task_id)
            return

    now = time.time()
    status_text = _status_value(status)
    previous_history = existing.get("history") if isinstance(existing.get("history"), list) else []
    if force:
        previous_history = []

    event = {
        "status": status_text,
        "timestamp": now,
    }
    if message:
        event["message"] = message

    data = {
        "status": status_text,
        "updated_at": now,
        "history": [*previous_history, event],
    }
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
