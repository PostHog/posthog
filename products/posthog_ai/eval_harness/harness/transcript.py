from __future__ import annotations

import os
import sys
import uuid
import logging
import threading
from collections.abc import Callable, Iterator
from contextlib import ExitStack, contextmanager, redirect_stderr, redirect_stdout
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, TextIO

from ..log_sink import LOGS_ROOT

HARNESS_LOGS_ROOT = LOGS_ROOT / "harness"


class _TranscriptSink:
    def __init__(self, path: Path, stdout: TextIO) -> None:
        self.path = path
        self.stdout = stdout
        self.file: IO[str] = path.open("a", encoding="utf-8", buffering=1)
        self.lock = threading.Lock()
        self.finished = False
        self.ends_with_newline = True
        self.console_output: Callable[[str], None] | None = None

    def write(self, terminal: TextIO, text: str, *, terminal_text: str | None = None) -> int:
        with self.lock:
            if self.finished:
                return len(text)
            self.file.write(text)
            self.file.flush()
            if text:
                self.ends_with_newline = text.endswith("\n")
        console_text = text if terminal_text is None else terminal_text
        if console_text:
            if self.console_output is not None:
                self.console_output(console_text)
            else:
                terminal.write(console_text)
                terminal.flush()
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
            self.file.flush()
            with self.path.open("rb") as saved:
                if saved.seek(0, os.SEEK_END):
                    saved.seek(-1, os.SEEK_END)
                    self.ends_with_newline = saved.read(1) == b"\n"
            prefix = "" if self.ends_with_newline else "\n"
            line = f"{prefix}Full run transcript (stdout and stderr):\n{self.path}\n"
            self.file.write(line)
            self.file.flush()
            self.finished = True
            self.file.close()
        self.stdout.write(line)
        self.stdout.flush()


class _TranscriptLogHandler(logging.Handler):
    def __init__(self, sink: _TranscriptSink, terminal: TextIO, verbose: bool) -> None:
        super().__init__()
        self._sink = sink
        self._terminal = terminal
        self._verbose = verbose

    def emit(self, record: logging.LogRecord) -> None:
        try:
            detail = self.format(record) + "\n"
            terminal_text = ""
            if self._verbose:
                terminal_text = detail
            elif record.levelno >= logging.WARNING and record.name.startswith("products.posthog_ai.eval_harness"):
                message = str(
                    record.msg.get("event", record.msg) if isinstance(record.msg, dict) else record.getMessage()
                )
                if record.exc_info and (error := record.exc_info[1]) is not None:
                    message = f"{message}: {type(error).__name__}: {error}"
                lines = message.splitlines()
                terminal_text = f"{record.levelname}: {record.name}: {lines[0][:240] if lines else ''}\n"
            self._sink.write(self._terminal, detail, terminal_text=terminal_text)
        except Exception:
            self.handleError(record)


class _TeeStream:
    """Plain-text stream that mirrors writes to a terminal and one shared file."""

    def __init__(self, terminal: TextIO, sink: _TranscriptSink) -> None:
        self._terminal = terminal
        self._sink = sink
        self._verbose = True

    @property
    def encoding(self) -> str:
        return self._terminal.encoding or "utf-8"

    @property
    def errors(self) -> str | None:
        return self._terminal.errors

    def write(self, text: str) -> int:
        return self._sink.write(self._terminal, text, terminal_text=None if self._verbose else "")

    def write_console(self, text: str) -> int:
        return self._sink.write(self._terminal, text)

    def flush(self) -> None:
        self._sink.flush(self._terminal)

    def fileno(self) -> int:
        return self._sink.file.fileno()

    def isatty(self) -> bool:
        # Static output is readable in terminals, redirected logs, and agent tools.
        return False

    def writable(self) -> bool:
        return True


def write_console(text: str, *, stream: TextIO | None = None) -> None:
    target = sys.stdout if stream is None else stream
    if isinstance(target, _TeeStream):
        target.write_console(text)
    else:
        target.write(text)
        target.flush()


class RunTranscript:
    """Tee one harness invocation to disk and publish its path last."""

    def __init__(self, path: Path, stdout: TextIO, stderr: TextIO) -> None:
        self.path = path.resolve()
        self._sink = _TranscriptSink(self.path, stdout)
        self._stdout = _TeeStream(stdout, self._sink)
        self._stderr = _TeeStream(stderr, self._sink)

    def logging_handler(self, *, verbose: bool = False) -> logging.Handler:
        return _TranscriptLogHandler(self._sink, self._stderr._terminal, verbose)

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
    def _capture_file_descriptor(self, stream: _TeeStream, descriptor: int) -> Iterator[None]:
        terminal = stream._terminal
        try:
            terminal_descriptor = terminal.fileno()
        except (AttributeError, OSError, ValueError):
            yield
            return
        terminal.flush()
        with os.fdopen(os.dup(terminal_descriptor), "w", encoding=stream.encoding, buffering=1) as console:
            saved_descriptor = os.dup(descriptor)
            stream._terminal = console
            if stream is self._stdout:
                self._sink.stdout = console
            try:
                # Native child processes inherit file descriptors and bypass Python stream redirection.
                os.dup2(self._sink.file.fileno(), descriptor)
                yield
            finally:
                os.dup2(saved_descriptor, descriptor)
                os.close(saved_descriptor)
                stream._terminal = terminal
                if stream is self._stdout:
                    self._sink.stdout = terminal

    @contextmanager
    def capture(self, *, verbose: bool = True, console_output: Callable[[str], None] | None = None) -> Iterator[None]:
        self._stdout._verbose = verbose
        self._stderr._verbose = verbose
        self._sink.console_output = console_output
        try:
            with ExitStack() as stack:
                stack.enter_context(self._capture_file_descriptor(self._stdout, 1))
                stack.enter_context(self._capture_file_descriptor(self._stderr, 2))
                stack.enter_context(redirect_stdout(self._stdout))
                stack.enter_context(redirect_stderr(self._stderr))
                yield
        finally:
            self._sink.console_output = None

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
