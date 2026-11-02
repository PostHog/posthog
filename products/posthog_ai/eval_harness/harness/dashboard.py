from __future__ import annotations

import os
import json
import time
import queue
import select
import shutil
import signal
import socket
import termios
import threading
import subprocess
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import TextIO

from ..log_sink import _case_log_slug
from .progress import TrialProgress
from .terminal import TerminalStreams, open_terminal
from .transcript import write_console

PHROCS_DIR = Path(__file__).resolve().parents[4] / "tools" / "phrocs"
READY_TIMEOUT_SECONDS = 5
VIEW_WRITE_TIMEOUT_SECONDS = 30
"""How long the view may stop reading progress events before the harness treats it as failed."""
VIEW_QUEUE_LIMIT = 10_000


def resolve_view_command() -> list[str]:
    """Find the phrocs binary that renders the view, building the in-repo copy when Go is available.

    `bin/start` uses the same order, so the eval view and `hogli start` run the same build.
    """
    if shutil.which("go") and shutil.which("make") and (PHROCS_DIR / "Makefile").exists():
        make = ["make", "-s", "-C", str(PHROCS_DIR), "build"]
        if subprocess.run([*make, "-q"], capture_output=True).returncode != 0:
            write_console("Building phrocs for the eval view...\n")
            subprocess.run(make, capture_output=True)
    built = PHROCS_DIR / "dist" / "phrocs"
    if built.exists():
        return [str(built)]
    if installed := shutil.which("phrocs"):
        return [installed]
    raise RuntimeError("phrocs is not installed. Run `hogli phrocs:build` or use --no-tui")


TerminalModes = list[int | list[bytes | int]]


def _terminal_modes(stream: TextIO) -> TerminalModes | None:
    try:
        return termios.tcgetattr(stream.fileno())
    except (OSError, ValueError, termios.error):
        return None


def _restore_terminal_modes(stream: TextIO, modes: TerminalModes) -> None:
    try:
        termios.tcsetattr(stream.fileno(), termios.TCSADRAIN, modes)
    except (OSError, ValueError, termios.error):
        pass


@contextmanager
def _detach_stdin() -> Iterator[None]:
    """Point stdin at /dev/null so that services the run starts cannot read the terminal.

    Child processes inherit stdin. A child that reads the terminal, such as `tsx watch`, takes key
    presses from the view, so the view seems to drop arrow keys.
    """
    saved = os.dup(0)
    devnull = os.open(os.devnull, os.O_RDONLY)
    try:
        os.dup2(devnull, 0)
        yield
    finally:
        os.dup2(saved, 0)
        os.close(saved)
        os.close(devnull)


class EvalDashboard:
    """Streams run progress to a `phrocs evals` child process that owns the terminal.

    The view runs in its own process, so the eval run cannot delay key presses or redraws.
    """

    def __init__(
        self,
        transcript: Path,
        *,
        command: Sequence[str],
        terminal: TerminalStreams,
        cancel: Callable[[], None],
    ) -> None:
        self.transcript = transcript
        self.result_text = ""
        self._command = list(command)
        self._terminal = terminal
        self._cancel = cancel
        self._socket: socket.socket | None = None
        self._outbox: queue.Queue[bytes | None] = queue.Queue(maxsize=VIEW_QUEUE_LIMIT)
        self._process: subprocess.Popen[bytes] | None = None
        self._reader: threading.Thread | None = None
        self._writer: threading.Thread | None = None
        self._ready = threading.Event()
        self._run_active = threading.Event()
        self._stopping = threading.Event()
        self._exit_code: int | None = None
        self._cancel_requested = False
        self._error: BaseException | None = None

    def _send(self, event: dict[str, object]) -> None:
        # The reporter calls this from the eval event loop, so it must never wait on the view.
        # A full queue means the view already stopped reading, and the writer reports that.
        try:
            self._outbox.put_nowait(json.dumps(event).encode() + b"\n")
        except queue.Full:
            pass

    def _write_events(self) -> None:
        assert self._socket is not None
        sock = self._socket
        while (data := self._outbox.get()) is not None:
            view = memoryview(data)
            deadline = time.monotonic() + VIEW_WRITE_TIMEOUT_SECONDS
            while view:
                remaining = deadline - time.monotonic()
                if self._stopping.is_set() or remaining <= 0:
                    if not self._stopping.is_set():
                        self._view_failed(
                            RuntimeError(
                                f"The terminal view stopped reading progress for {VIEW_WRITE_TIMEOUT_SECONDS} seconds"
                            )
                        )
                    return
                try:
                    _, writable, _ = select.select([], [sock], [], min(remaining, 1.0))
                    if writable:
                        view = view[sock.send(view) :]
                except BlockingIOError:
                    continue
                except (OSError, ValueError):
                    # The reader thread sees the closed view and reports the failure.
                    return

    def _view_failed(self, error: BaseException) -> None:
        if self._error is None:
            self._error = error
        if self._run_active.is_set():
            self.request_cancel()

    def configure(self, description: str) -> None:
        self._send({"type": "run", "description": description, "transcript": str(self.transcript)})

    def setup_started(self, phase: str) -> None:
        self._send({"type": "setup", "phase": phase})

    def setup_finished(self) -> None:
        self._send({"type": "setup_done"})

    def set_stage(self, stage: str) -> None:
        self._send({"type": "stage", "stage": stage})

    def experiment_started(self, name: str, total: int) -> None:
        self._send({"type": "experiment", "name": name, "total": total})

    def update_trial(self, trial: TrialProgress) -> None:
        wall_offset = time.time() - time.monotonic()
        event: dict[str, object] = {
            "type": "trial",
            "id": trial.trial_id,
            "experiment": trial.experiment,
            "name": trial.name,
            "index": trial.trial_index,
            "phase": trial.phase,
            "started": trial.started + wall_offset,
            "ended": trial.ended + wall_offset if trial.ended is not None else 0,
            "detail": trial.detail,
        }
        if trial.log_dir is not None:
            slug = _case_log_slug(trial.name, trial.trial_id)
            event["summary_path"] = str(trial.log_dir / f"{slug}.summary.txt")
            event["log_path"] = str(trial.log_dir / f"{slug}.jsonl")
        self._send(event)

    def trial_retry(self, trial_id: str, detail: str) -> None:
        self._send({"type": "retry", "id": trial_id, "detail": detail})

    def write(self, text: str) -> None:
        if text.lstrip().startswith(("Sandboxed eval summary", "ERROR:", "error:")):
            self.result_text = text
        self._send({"type": "message", "text": text})

    @property
    def failure(self) -> BaseException | None:
        return self._error

    def begin_run(self) -> bool:
        self._run_active.set()
        if self.failure is not None:
            self._run_active.clear()
            return False
        return True

    def end_run(self) -> None:
        self._run_active.clear()

    def request_cancel(self) -> None:
        if not self._cancel_requested:
            self._cancel_requested = True
            self._cancel()

    def _read_replies(self) -> None:
        assert self._socket is not None and self._process is not None
        sock = self._socket
        pending = b""
        while True:
            try:
                readable, _, _ = select.select([sock], [], [], 1.0)
                if not readable:
                    continue
                chunk = sock.recv(4096)
            except BlockingIOError:
                continue
            except (OSError, ValueError):
                break
            if not chunk:
                break
            pending += chunk
            while b"\n" in pending:
                line, pending = pending.split(b"\n", 1)
                reply = line.strip()
                if reply == b"ready":
                    self._ready.set()
                elif reply == b"cancel":
                    self.request_cancel()
        returncode = self._process.wait()
        if self._exit_code is None and not self._stopping.is_set():
            stderr = self._process.stderr.read().decode(errors="replace").strip() if self._process.stderr else ""
            self._view_failed(
                RuntimeError(
                    f"The terminal view exited with code {returncode} before the eval run completed"
                    + (f": {stderr}" if stderr else "")
                )
            )
        self._ready.set()

    @contextmanager
    def display(self) -> Iterator[None]:
        saved_modes = _terminal_modes(self._terminal.input)
        parent, child = socket.socketpair()
        environment = dict(os.environ)
        if environment.get("TERM", "dumb") == "dumb":
            environment["TERM"] = "xterm-256color"
        try:
            try:
                self._process = subprocess.Popen(
                    [*self._command, "evals", "--fd", str(child.fileno())],
                    stdin=self._terminal.input,
                    stdout=self._terminal.output,
                    stderr=subprocess.PIPE,
                    pass_fds=(child.fileno(),),
                    env=environment,
                )
            finally:
                child.close()
            # Non-blocking, so a view that stops reading can never block the writer thread.
            parent.setblocking(False)
            self._socket = parent
            self._reader = threading.Thread(target=self._read_replies, name="eval-view-replies", daemon=True)
            self._reader.start()
            self._writer = threading.Thread(target=self._write_events, name="eval-view-events", daemon=True)
            self._writer.start()
            if not self._ready.wait(timeout=READY_TIMEOUT_SECONDS):
                raise RuntimeError(f"The terminal view did not start within {READY_TIMEOUT_SECONDS} seconds")
            if self._error is not None:
                raise RuntimeError(f"Could not start the terminal view: {self._error}") from self._error
            with _detach_stdin():
                yield
        finally:
            self._stopping.set()
            if self._process is not None and self._process.poll() is None:
                self._process.terminate()
                try:
                    self._process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._process.kill()
                    self._process.wait()
            # A view that died from a signal cannot restore the terminal, so the shell would
            # inherit raw mode. Restore the modes from before the view started.
            if saved_modes is not None:
                _restore_terminal_modes(self._terminal.input, saved_modes)
            if self._writer is not None:
                try:
                    self._outbox.put_nowait(None)
                except queue.Full:
                    pass
                self._writer.join(timeout=5)
            self._socket = None
            parent.close()
            if self._reader is not None:
                self._reader.join(timeout=5)

    def finish(self, exit_code: int) -> None:
        self._exit_code = exit_code
        summary = self.result_text if self.result_text.lstrip().startswith("Sandboxed eval summary") else ""
        event = json.dumps({"type": "finish", "exit_code": exit_code, "text": summary}).encode() + b"\n"
        try:
            # The view stays open until it receives this event, so wait for queue room here.
            self._outbox.put(event, timeout=VIEW_WRITE_TIMEOUT_SECONDS)
        except queue.Full:
            return
        # A failed view never reads the finish event, so stop waiting and let display() terminate it.
        while self._process is not None and self._error is None:
            try:
                self._process.wait(timeout=0.5)
                return
            except subprocess.TimeoutExpired:
                continue


@contextmanager
def open_dashboard(transcript: Path) -> Iterator[EvalDashboard]:
    command = resolve_view_command()
    with open_terminal() as terminal:
        dashboard = EvalDashboard(
            transcript,
            command=command,
            terminal=terminal,
            cancel=lambda: os.kill(os.getpid(), signal.SIGINT),
        )
        with dashboard.display():
            yield dashboard
