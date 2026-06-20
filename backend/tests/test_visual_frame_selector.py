import pathlib
import shutil
import sys


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.visual_frame_selector import (
    ScreenshotCandidateSelectionRequest,
    ScreenshotSelectionError,
    VisualFrameSelector,
)


TEST_TMP_ROOT = ROOT / ".test_tmp"


class ProjectTempDir:
    def __init__(self, prefix="frame_selector_"):
        self.prefix = prefix
        self.path: pathlib.Path | None = None

    def __enter__(self):
        import uuid

        TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)
        self.path = TEST_TMP_ROOT / f"{self.prefix}{uuid.uuid4().hex}"
        self.path.mkdir()
        return self.path

    def __exit__(self, _exc_type, _exc, _tb):
        if self.path is not None:
            shutil.rmtree(self.path, ignore_errors=True)


class _Reader:
    @staticmethod
    def _calculate_file_md5(path):
        return pathlib.Path(path).name

    @staticmethod
    def _score_frame(path):
        timestamp = int(pathlib.Path(path).stem.split("_")[-1])
        if timestamp >= 40:
            return 0.86, timestamp
        return 0.42, timestamp


def test_frame_selector_returns_candidate_and_diagnostic_report():
    with ProjectTempDir() as tmp_path:
        created = []

        def _generate(_video_path, _output_dir, timestamp, index):
            path = tmp_path / f"shot_{index}_{timestamp}.jpg"
            path.write_bytes(f"image-{timestamp}".encode())
            created.append(path)
            return str(path)

        selector = VisualFrameSelector(lambda _text: (0.0, []))
        generated_paths = []

        result = selector.select_near_timestamp(
            ScreenshotCandidateSelectionRequest(
                video_path=pathlib.Path("video.mp4"),
                timestamp=0,
                duration=90,
                index=0,
                visual_reader=_Reader(),
                image_output_dir=tmp_path,
                screenshot_func=_generate,
                search_end=60,
                generated_image_paths=generated_paths,
            )
        )

        assert result.candidate.timestamp >= 40
        assert result.report["candidate_count"] >= 2
        assert result.report["selected_timestamp"] == result.candidate.timestamp
        assert result.report["selected_by"] == "heuristic"
        assert result.report["candidates"]
        assert result.report["segments"]
        assert pathlib.Path(result.candidate.path).exists()
        assert [path for path in created if path.exists()] == [pathlib.Path(result.candidate.path)]
        assert generated_paths


def test_frame_selector_error_carries_candidate_report():
    with ProjectTempDir() as tmp_path:
        def _missing(_video_path, _output_dir, timestamp, index):
            return str(tmp_path / f"missing_{index}_{timestamp}.jpg")

        selector = VisualFrameSelector(lambda _text: (0.0, []))

        try:
            selector.select_near_timestamp(
                ScreenshotCandidateSelectionRequest(
                    video_path=pathlib.Path("video.mp4"),
                    timestamp=0,
                    duration=30,
                    index=0,
                    visual_reader=_Reader(),
                    image_output_dir=tmp_path,
                    screenshot_func=_missing,
                )
            )
        except ScreenshotSelectionError as exc:
            assert "未生成可用截图候选" in str(exc)
            assert exc.report["candidate_count"] == 0
            assert exc.report["candidates"]
            assert exc.report["candidates"][0]["status"] == "missing-file"
        else:
            raise AssertionError("expected ScreenshotSelectionError")
