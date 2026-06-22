import shutil
import tempfile
import uuid
from pathlib import Path


TEST_TEMP_ROOT = Path(__file__).resolve().parents[1] / ".test_tmp" / "tempfile"


class ProjectTemporaryDirectory:
    """A pytest-only replacement for tempfile.TemporaryDirectory on Windows sandbox runs.

    In the Codex Windows sandbox, directories created by tempfile.mkdtemp can
    end up with ACLs that the same Python process cannot write into. Creating
    the directory with pathlib keeps the test temp tree writable while
    preserving TemporaryDirectory's context-manager API.
    """

    def __init__(
        self,
        suffix=None,
        prefix=None,
        dir=None,
        ignore_cleanup_errors=False,
        **_kwargs,
    ):
        self.suffix = suffix or ""
        self.prefix = prefix or "tmp"
        self.root = Path(dir) if dir is not None else TEST_TEMP_ROOT
        self.ignore_cleanup_errors = ignore_cleanup_errors
        self.name = ""
        self._path: Path | None = None

    def __enter__(self):
        self.root.mkdir(parents=True, exist_ok=True)
        for _ in range(100):
            candidate = self.root / f"{self.prefix}{uuid.uuid4().hex}{self.suffix}"
            try:
                candidate.mkdir()
            except FileExistsError:
                continue
            self._path = candidate
            self.name = str(candidate)
            return self.name
        raise FileExistsError("Unable to create a unique temporary directory")

    def __exit__(self, _exc_type, _exc, _tb):
        self.cleanup()

    def cleanup(self):
        if self._path is None:
            return
        shutil.rmtree(self._path, ignore_errors=self.ignore_cleanup_errors or True)
        self._path = None


tempfile.TemporaryDirectory = ProjectTemporaryDirectory
