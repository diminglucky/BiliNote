import argparse
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

import httpx

from app.benchmark.note_quality import load_task_report, write_report_files


TERMINAL_STATUSES = {"SUCCESS", "FAILED"}


@dataclass
class PollEvent:
    elapsed_seconds: float
    status: str
    message: str = ""
    has_result: bool = False
    markdown_chars: int = 0
    image_count: int = 0


@dataclass
class E2EBenchmarkReport:
    task_id: str
    generation_token: str
    status: str
    total_seconds: float
    first_result_seconds: Optional[float]
    first_image_seconds: Optional[float]
    poll_events: list[PollEvent] = field(default_factory=list)
    quality_report_path: Optional[str] = None
    issues: list[str] = field(default_factory=list)

    @property
    def pass_quality_gate(self) -> bool:
        return self.status == "SUCCESS" and not self.issues


def run_e2e_benchmark(
    backend_url: str,
    payload: dict[str, Any],
    note_output_dir: str | Path,
    static_dir: str | Path,
    report_dir: str | Path,
    timeout_seconds: int = 1800,
    poll_interval: float = 3.0,
) -> E2EBenchmarkReport:
    backend_url = backend_url.rstrip("/")
    report_path = Path(report_dir)
    report_path.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    with httpx.Client(timeout=60.0) as client:
        response = client.post(f"{backend_url}/api/generate_note", json=payload)
        response.raise_for_status()
        body = response.json()
        data = unwrap_response(body)
        task_id = data.get("task_id")
        generation_token = data.get("generation_token")
        if not task_id or not generation_token:
            raise RuntimeError(f"generate_note response missing task_id/generation_token: {body}")

        events: list[PollEvent] = []
        first_result_seconds: Optional[float] = None
        first_image_seconds: Optional[float] = None
        final_status = "PENDING"
        final_message = ""
        last_signature: Optional[tuple[Any, ...]] = None

        while True:
            elapsed = time.monotonic() - started
            if elapsed > timeout_seconds:
                final_status = "TIMEOUT"
                final_message = f"Benchmark timed out after {timeout_seconds}s"
                break

            status_response = client.get(
                f"{backend_url}/api/task_status/{task_id}",
                params={"generation_token": generation_token},
                timeout=60.0,
            )
            status_response.raise_for_status()
            status_body = unwrap_response(status_response.json())
            status = str(status_body.get("status") or "UNKNOWN")
            message = str(status_body.get("message") or "")
            result = status_body.get("result") or {}
            markdown = str(result.get("markdown") or "") if isinstance(result, dict) else ""
            image_count = markdown.count("![](") + markdown.count("![")
            has_result = bool(markdown.strip())
            if has_result and first_result_seconds is None:
                first_result_seconds = elapsed
            if image_count > 0 and first_image_seconds is None:
                first_image_seconds = elapsed

            signature = (status, message, has_result, len(markdown), image_count)
            if signature != last_signature:
                events.append(PollEvent(
                    elapsed_seconds=round(elapsed, 3),
                    status=status,
                    message=message,
                    has_result=has_result,
                    markdown_chars=len(markdown),
                    image_count=image_count,
                ))
                last_signature = signature

            final_status = status
            final_message = message
            if status in TERMINAL_STATUSES:
                break
            time.sleep(poll_interval)

    issues: list[str] = []
    quality_report_path = None
    if final_status == "SUCCESS":
        quality_report = load_task_report(task_id, note_output_dir, static_dir)
        quality_json_path, _quality_md_path = write_report_files(quality_report, report_path)
        quality_report_path = str(quality_json_path)
        issues.extend(quality_report.issues)
    else:
        issues.append(f"terminal-status:{final_status}:{final_message}")

    report = E2EBenchmarkReport(
        task_id=task_id,
        generation_token=generation_token,
        status=final_status,
        total_seconds=round(time.monotonic() - started, 3),
        first_result_seconds=first_result_seconds,
        first_image_seconds=first_image_seconds,
        poll_events=events,
        quality_report_path=quality_report_path,
        issues=issues,
    )
    output = report_path / f"{task_id}.e2e.json"
    output.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def unwrap_response(body: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise RuntimeError(f"Unexpected response body: {body}")
    if body.get("code", 0) != 0:
        raise RuntimeError(f"API error: {body.get('msg') or body}")
    data = body.get("data")
    return data if isinstance(data, dict) else {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a real API end-to-end note benchmark.")
    parser.add_argument("--backend-url", default="http://127.0.0.1:8483")
    parser.add_argument("--payload", required=True, help="Path to generate_note JSON payload.")
    parser.add_argument("--note-output-dir", default="note_results")
    parser.add_argument("--static-dir", default="static")
    parser.add_argument("--report-dir", default="benchmark_reports")
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--poll-interval", type=float, default=3.0)
    args = parser.parse_args()

    payload = json.loads(Path(args.payload).read_text(encoding="utf-8"))
    report = run_e2e_benchmark(
        backend_url=args.backend_url,
        payload=payload,
        note_output_dir=args.note_output_dir,
        static_dir=args.static_dir,
        report_dir=args.report_dir,
        timeout_seconds=args.timeout_seconds,
        poll_interval=args.poll_interval,
    )
    print(f"task_id={report.task_id}")
    print(f"status={report.status}")
    print(f"total_seconds={report.total_seconds}")
    print(f"quality_pass={str(report.pass_quality_gate).lower()}")
    if report.issues:
        print("issues=" + ", ".join(report.issues[:12]))
    return 0 if report.pass_quality_gate else 2


if __name__ == "__main__":
    raise SystemExit(main())
