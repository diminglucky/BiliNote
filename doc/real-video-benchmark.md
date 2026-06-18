# Real Video Benchmark

This project should not be called product-ready only because unit tests pass.
Use this benchmark whenever the note-generation agent is changed.

## Audit An Existing Task

Run from `backend/`:

```bash
python -m app.benchmark.note_quality <task_id> --note-output-dir note_results --static-dir static --report-dir benchmark_reports
```

The command writes:

- `<task_id>.quality.json` for automation.
- `<task_id>.quality.md` for manual review.

It checks:

- Missing Markdown images.
- Low-resolution, blurry, blank, or low-information screenshots.
- Duplicate or near-duplicate screenshots.
- Leftover `Screenshot-[mm:ss]` markers.
- Whether images have nearby Markdown context.
- Task status history and stage timing.

## Run A Real API Benchmark

Start the backend first, then create a payload file such as:

```json
{
  "video_url": "https://www.bilibili.com/video/BV...",
  "platform": "bilibili",
  "quality": "medium",
  "model_name": "your-model",
  "provider_id": "your-provider-id",
  "screenshot": true,
  "link": true,
  "format": ["screenshot", "link"],
  "style": "detailed",
  "grid_size": []
}
```

Run from `backend/`:

```bash
python -m app.benchmark.e2e_runner --payload benchmark_payload.json --backend-url http://127.0.0.1:8483 --report-dir benchmark_reports
```

The e2e report records:

- Total runtime.
- First visible Markdown time.
- First screenshot time.
- Every meaningful polling state transition.
- Final quality report path.

## Product Acceptance Focus

A real video pass should be judged by:

- Base note appears before screenshot enhancement finishes.
- Frontend polling has visible progress during long phases.
- Screenshots are inserted where the note actually needs visual evidence.
- Long videos do not create repeated screenshots for the same unchanged screen.
- Failed enhancement keeps the base note usable and reports a clear message.
- Regeneration uses a new generation token and does not return stale cached content.
