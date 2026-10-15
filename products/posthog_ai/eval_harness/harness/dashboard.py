from __future__ import annotations

import os
import time
import signal
import threading
from collections import Counter, deque
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from dataclasses import replace
from pathlib import Path

from prompt_toolkit.application import Application
from prompt_toolkit.document import Document
from prompt_toolkit.filters import is_searching
from prompt_toolkit.input import Input, create_input
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.key_binding.key_processor import KeyPressEvent
from prompt_toolkit.layout import HSplit, Layout
from prompt_toolkit.output import Output
from prompt_toolkit.output.vt100 import Vt100_Output
from prompt_toolkit.search import start_search
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Frame, Label, RadioList, SearchToolbar, TextArea

from ..log_sink import _case_log_slug
from .progress import TERMINAL_PHASES, TrialProgress
from .terminal import open_terminal


class EvalDashboard:
    def __init__(self, transcript: Path, *, input: Input, output: Output, cancel: Callable[[], None]) -> None:
        self.transcript = transcript
        self._cancel = cancel
        self._lock = threading.Lock()
        self._trials: dict[str, TrialProgress] = {}
        self._experiments: dict[str, int] = {}
        self._messages: deque[str] = deque(maxlen=200)
        self._setup: list[str] = []
        self._started = time.monotonic()
        self._description = "Preparing eval run"
        self._stage = "Starting"
        self.result_text = ""
        self._setup_complete = False
        self._exit_code: int | None = None
        self._confirm_cancel = False
        self._cancel_requested = False
        self._show_logs = False
        self._follow = True
        self._ready = threading.Event()
        self._thread_error: Exception | None = None
        self._thread: threading.Thread | None = None
        self._choices = RadioList[str]([("", "Run and setup")])
        self._search = SearchToolbar()
        self._details = TextArea(read_only=True, scrollbar=True, search_field=self._search, wrap_lines=True)
        self._header = Label(text="", style="class:header")
        self._footer = Label(text="")
        self.application: Application[None] = Application(
            layout=Layout(
                HSplit(
                    [
                        self._header,
                        Frame(self._choices, title="Trials", height=9),
                        Frame(self._details, title="Details"),
                        self._search,
                        self._footer,
                    ]
                ),
                focused_element=self._choices,
            ),
            key_bindings=self._bindings(),
            input=input,
            output=output,
            full_screen=True,
            mouse_support=True,
            refresh_interval=0.5,
            before_render=lambda _app: self._refresh(),
            style=Style.from_dict(
                {
                    "frame.border": "#808080",
                    "frame.label": "#f9bd2b bold",
                    "radio-selected": "#f54e00 bold",
                    "header": "#f9bd2b bold",
                }
            ),
        )

    def configure(self, description: str) -> None:
        with self._lock:
            self._description = description

    def setup_started(self, phase: str) -> None:
        with self._lock:
            self._setup.append(phase)
            self._stage = phase

    def setup_finished(self) -> None:
        with self._lock:
            self._setup_complete = True
            self._stage = "Running trials"

    def set_stage(self, stage: str) -> None:
        with self._lock:
            self._stage = stage

    def experiment_started(self, name: str, total: int) -> None:
        with self._lock:
            self._experiments[name] = total

    def update_trial(self, trial: TrialProgress) -> None:
        with self._lock:
            previous = self._trials.get(trial.trial_id)
            if previous:
                trial = replace(trial, retries=previous.retries)
            self._trials[trial.trial_id] = trial

    def trial_retry(self, trial_id: str, detail: str) -> None:
        with self._lock:
            if trial := self._trials.get(trial_id):
                self._trials[trial_id] = replace(trial, detail=detail, retries=trial.retries + 1)

    def write(self, text: str) -> None:
        with self._lock:
            self._messages.extend(text.splitlines())
            if text.lstrip().startswith(("Sandboxed eval summary", "ERROR:", "error:")):
                self.result_text = text
        if self._thread_error is not None:
            self.application.output.write(text)
            self.application.output.flush()

    def _bindings(self) -> KeyBindings:
        bindings = KeyBindings()

        @bindings.add("tab", filter=~is_searching)
        def focus(event: KeyPressEvent) -> None:
            event.app.layout.focus(self._details if event.app.layout.has_focus(self._choices) else self._choices)

        @bindings.add("l", filter=~is_searching)
        def logs(_event: KeyPressEvent) -> None:
            self._show_logs = not self._show_logs

        @bindings.add("f", filter=~is_searching)
        def follow(_event: KeyPressEvent) -> None:
            self._follow = not self._follow

        @bindings.add("/", filter=~is_searching)
        def search(_event: KeyPressEvent) -> None:
            self.application.layout.focus(self._details)
            start_search(self._details.control)

        @bindings.add("q", filter=~is_searching)
        def quit_or_confirm(event: KeyPressEvent) -> None:
            if self._exit_code is not None:
                event.app.exit()
            elif not self._cancel_requested:
                self._confirm_cancel = not self._confirm_cancel

        @bindings.add("y", filter=~is_searching)
        def confirm(_event: KeyPressEvent) -> None:
            if self._confirm_cancel:
                self.request_cancel()

        @bindings.add("n", filter=~is_searching)
        @bindings.add("escape", filter=~is_searching)
        def dismiss(_event: KeyPressEvent) -> None:
            self._confirm_cancel = False

        @bindings.add("c-c", filter=~is_searching)
        def interrupt(event: KeyPressEvent) -> None:
            if self._exit_code is not None:
                event.app.exit()
            else:
                self.request_cancel()

        return bindings

    def request_cancel(self) -> None:
        if not self._cancel_requested:
            self._cancel_requested = True
            self._confirm_cancel = False
            self._cancel()

    @staticmethod
    def _tail(path: Path) -> str:
        try:
            with path.open("rb") as log:
                log.seek(0, os.SEEK_END)
                size = log.tell()
                log.seek(max(0, size - 65536))
                text = log.read(65536).decode("utf-8", errors="replace")
                if size > 65536:
                    text = "Showing recent output. Open the log file for earlier lines.\n\n" + text
                return text
        except OSError:
            return "Logs are not available yet. They will appear after execution."

    def _refresh(self) -> None:
        with self._lock:
            trials = dict(self._trials)
            total = sum(self._experiments.values())
            setup_phases = list(self._setup)
            diagnostics = "\n".join(
                line
                for line in self._messages
                if line.startswith(
                    ("WARNING:", "ERROR:", "error:", "CASE RETRY", "CASE ERROR", "CASE TIMEOUT", "SUITE CRASH")
                )
            )
        counts: Counter[str] = Counter(trial.phase for trial in trials.values())
        finished = sum(counts[phase] for phase in TERMINAL_PHASES)
        status = "Running" if self._exit_code is None else ("PASS" if self._exit_code == 0 else "FAIL")
        if self._exit_code == 130:
            status = "Interrupted"
        self._header.text = (
            f"Eval run | {status} | {finished}/{total} finished | {time.monotonic() - self._started:.0f}s\n"
            f"{self._description}\n{self._stage}"
        )
        choices = [("", "Run and setup")]
        now = time.monotonic()
        for row in trials.values():
            elapsed = (row.ended or now) - row.started
            choices.append(
                (
                    row.trial_id,
                    f"{row.phase:<8} {elapsed:>4.0f}s  #{row.trial_index + 1} retry={row.retries}  {row.name} ({row.experiment})",
                )
            )
        self._choices.values = choices
        trial = trials.get(self._choices.current_value)
        if trial is None:
            setup = "\n".join(
                f"{'DONE' if self._setup_complete or index < len(self._setup) - 1 else status}: {phase}"
                for index, phase in enumerate(setup_phases)
            )
            phases = " | ".join(
                f"{phase}: {counts[phase]}" for phase in ("queued", "setup", "agent", "cleanup", "logs", "scoring")
            )
            overview = f"Setup\n{setup}\n\nTrials\n{phases}\n\n{diagnostics}"
            if self._exit_code is not None:
                overview += "\n\n" + self.result_text
            text = f"{self.transcript}\n\n" + self._tail(self.transcript) if self._show_logs else overview
        else:
            heading = (
                f"{trial.experiment} :: {trial.name} [trial {trial.trial_index + 1}]\n"
                f"Phase: {trial.phase} | Setup retries: {trial.retries}\n{trial.detail}\n"
            )
            if trial.log_dir is not None:
                suffix = ".jsonl" if self._show_logs else ".summary.txt"
                path = trial.log_dir / f"{_case_log_slug(trial.name, trial.trial_id)}{suffix}"
                text = heading + f"\n{path}\n\n" + self._tail(path)
                if not path.exists():
                    text += "\nSelect Run and setup, then press l to read live service and agent logs."
            else:
                text = heading + "\nSelect Run and setup, then press l to read live service and agent logs."
        if text != self._details.text and not is_searching():
            cursor = len(text) if self._follow else min(self._details.buffer.cursor_position, len(text))
            self._details.buffer.set_document(Document(text, cursor_position=cursor), bypass_readonly=True)
        if self._confirm_cancel:
            footer = "Cancel this run and clean up? y yes | n continue"
        elif self._cancel_requested and self._exit_code is None:
            footer = "Cancel requested. Waiting for cleanup."
        else:
            footer = "Up/Down Enter select | Tab focus | l logs | / search\nf follow | q "
            footer += "close" if self._exit_code is not None else "cancel | Ctrl-C cancel"
        self._footer.text = footer

    def _run(self) -> None:
        try:
            self.application.run(pre_run=self._ready.set, set_exception_handler=False, handle_sigint=False)
        except Exception as error:
            self._thread_error = error
        finally:
            self._ready.set()

    @contextmanager
    def display(self) -> Iterator[None]:
        self._thread = threading.Thread(target=self._run, name="eval-dashboard", daemon=True)
        self._thread.start()
        try:
            if not self._ready.wait(timeout=5) or self._thread_error:
                raise RuntimeError("Could not start the eval dashboard") from self._thread_error
            yield
        finally:
            if self.application.is_running and (loop := self.application.loop) is not None:
                loop.call_soon_threadsafe(self.application.exit)
            self._thread.join(timeout=5)

    def finish(self, exit_code: int) -> None:
        self._exit_code = exit_code
        self.set_stage(
            "Results ready. Press q to close." if exit_code == 0 else "Run stopped. Select Run and setup for details."
        )
        self.application.invalidate()
        if self._thread is not None:
            self._thread.join()


@contextmanager
def open_dashboard(transcript: Path) -> Iterator[EvalDashboard]:
    with (
        open_terminal() as terminal,
        closing(create_input(terminal.input)) as input,
    ):
        dashboard = EvalDashboard(
            transcript,
            input=input,
            output=Vt100_Output.from_pty(
                terminal.output, term="xterm-256color" if os.getenv("TERM") == "dumb" else os.getenv("TERM")
            ),
            cancel=lambda: os.kill(os.getpid(), signal.SIGINT),
        )
        with dashboard.display():
            yield dashboard
