from __future__ import annotations

import sys
import uuid
import threading
from collections.abc import Iterator
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, TextIO

from ..log_sink import LOGS_ROOT

HARNESS_LOGS_ROOT = LOGS_ROOT / "harness"


class _TranscriptSink:
    def __init__(self, path: Path, stdout: TextIO) -> None:
        self.path = path
        self.stdout = stdout
        self.file: IO[str] = path.open("w", encoding="utf-8", buffering=1)
        self.lock = threading.Lock()
        self.finished = False
        self.ends_with_newline = True

    def write(self, terminal: TextIO, text: str) -> int:
        with self.lock:
            if self.finished:
                return len(text)
            self.file.write(text)
            self.file.flush()
            terminal.write(text)
            terminal.flush()
            if text:
                self.ends_with_newline = text.endswith("\n")
        return len(text)

    def flush(self, terminal: TextIO) -> None:
        with self.lock:
            if self.finished:
                return
            self.file.flush()
            terminal.flush()

    def finish(self) -> None:
        with self.lock:
            if self.finished:
                return
            prefix = "" if self.ends_with_newline else "\n"
            line = f"{prefix}Full run transcript (stdout and stderr):\n{self.path}\n"
            self.file.write(line)
            self.file.flush()
            self.stdout.write(line)
            self.stdout.flush()
            self.finished = True
            self.file.close()


class _TeeStream:
    """Plain-text stream that mirrors writes to a terminal and one shared file."""

    def __init__(self, terminal: TextIO, sink: _TranscriptSink) -> None:
        self._terminal = terminal
        self._sink = sink

    @property
    def encoding(self) -> str:
        return self._terminal.encoding or "utf-8"

    @property
    def errors(self) -> str | None:
        return self._terminal.errors

    def write(self, text: str) -> int:
        return self._sink.write(self._terminal, text)

    def flush(self) -> None:
        self._sink.flush(self._terminal)

    def fileno(self) -> int:
        return self._terminal.fileno()

    def isatty(self) -> bool:
        # Static output is readable in terminals, redirected logs, and agent tools.
        return False

    def writable(self) -> bool:
        return True


class RunTranscript:
    """Tee one harness invocation to disk and publish its path last."""

    def __init__(self, path: Path, stdout: TextIO, stderr: TextIO) -> None:
        self.path = path.resolve()
        self._sink = _TranscriptSink(self.path, stdout)
        self._stdout = _TeeStream(stdout, self._sink)
        self._stderr = _TeeStream(stderr, self._sink)

    @classmethod
    def create(cls, root: Path = HARNESS_LOGS_ROOT) -> RunTranscript:
        root = root.resolve()
        root.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
        path = root / f"{timestamp}_{uuid.uuid4().hex[:8]}.log"
        transcript = cls(path, sys.stdout, sys.stderr)
        transcript._update_latest_symlink(root)
        return transcript

    @contextmanager
    def capture(self) -> Iterator[None]:
        with redirect_stdout(self._stdout), redirect_stderr(self._stderr):
            yield

    def finish(self) -> None:
        self._sink.finish()

    def _update_latest_symlink(self, root: Path) -> None:
        latest = root / "latest.log"
        try:
            if latest.is_symlink() or latest.exists():
                latest.unlink()
            latest.symlink_to(self.path.name)
        except OSError:
            # The real transcript remains usable on filesystems without symlink support.
            pass
