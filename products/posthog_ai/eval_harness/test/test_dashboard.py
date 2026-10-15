from __future__ import annotations

import os
import sys
import asyncio
import threading
from pathlib import Path
from textwrap import dedent

import pytest

import pexpect
from prompt_toolkit.application import Application
from prompt_toolkit.data_structures import Size
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from products.posthog_ai.eval_harness.harness.dashboard import EvalDashboard
from products.posthog_ai.eval_harness.harness.reporting import ProgressReporter
from products.posthog_ai.eval_harness.log_sink import write_case_logs


class _TerminalOutput(DummyOutput):
    def __init__(self, columns: int) -> None:
        self.columns = columns

    def get_size(self) -> Size:
        return Size(rows=32, columns=self.columns)


def _screen_text(application: Application[None]) -> str:
    screen = application.renderer.last_rendered_screen
    assert screen is not None
    return "\n".join("".join(row[x].char for x in sorted(row)) for row in screen.data_buffer.values())


def _mouse_sequence(application: Application[None], text: str, *, button: int = 0) -> str:
    for y, row in enumerate(_screen_text(application).splitlines()):
        if text in row:
            x = row.index(text) + 1
            sequence = f"\x1b[<{button};{x};{y + 1}M"
            return sequence + (f"\x1b[<0;{x};{y + 1}m" if button == 0 else "")
    raise AssertionError(f"No visible control: {text}")


@pytest.mark.asyncio
@pytest.mark.parametrize("columns", [60, 120])
async def test_dashboard_shows_trial_results_and_supports_logs_search_and_safe_cancel(
    tmp_path: Path, columns: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("EXPORT_EVAL_RESULTS", raising=False)
    transcript = tmp_path / "run.log"
    transcript.write_text("Service ready\nTransient failure recovered\n")
    cancellations: list[bool] = []
    rendered = asyncio.Event()
    pressed = asyncio.Event()
    with create_pipe_input() as keys:
        dashboard = EvalDashboard(
            transcript, input=keys, output=_TerminalOutput(columns), cancel=lambda: cancellations.append(True)
        )
        dashboard.application.after_render += lambda _app: rendered.set()
        dashboard.application.key_processor.after_key_press += lambda _processor: pressed.set()
        dashboard.application.refresh_interval = None
        task = asyncio.create_task(dashboard.application.run_async(handle_sigint=False))

        async def wait_text(text: str) -> str:
            async with asyncio.timeout(5):
                while True:
                    screen = _screen_text(dashboard.application)
                    if text in screen:
                        return screen
                    rendered.clear()
                    await rendered.wait()

        async def refresh() -> str:
            rendered.clear()
            dashboard.application.invalidate()
            await asyncio.wait_for(rendered.wait(), timeout=5)
            return _screen_text(dashboard.application)

        async def send(text: str) -> str:
            pressed.clear()
            keys.send_text(text)
            await asyncio.wait_for(pressed.wait(), timeout=5)
            return await refresh()

        try:
            await asyncio.wait_for(rendered.wait(), timeout=5)
            reporter = ProgressReporter(total_suites=1, dashboard=dashboard)
            reporter.setup_started("start example service")
            await wait_text("start example service")
            dashboard.setup_finished()
            await reporter.experiment_started("example", 2, tmp_path)
            await reporter.case_started("example", "same-case", "first", 0)
            await reporter.case_started("example", "same-case", "second", 1)
            await reporter.case_phase("first", "agent")
            await reporter.case_setup_retry(
                "example",
                "same-case",
                next_attempt=2,
                total_attempts=3,
                delay_seconds=1,
                error_type="ConnectionError",
                trial_id="first",
            )
            await reporter.case_done("example", "same-case", duration_seconds=2, trial_id="first")
            assert "scoring" in await refresh()
            write_case_logs(
                tmp_path, "same-case", "trial log contents", {}, "Example prompt", 2, "Trial answer", trial_id="first"
            )
            await reporter.case_scored("first")
            await reporter.case_done(
                "example", "same-case", duration_seconds=1, trial_id="second", status="error", error_type="RuntimeError"
            )
            await send("\x1b[B\r")
            screen = await wait_text("Trial answer")
            assert "retry=1" in screen
            await send(_mouse_sequence(dashboard.application, "#1", button=65))
            await wait_text("Phase: error")
            await send(_mouse_sequence(dashboard.application, "#1"))
            await wait_text("Trial answer")
            await send("l")
            await wait_text("trial log contents")
            await send("\x1b[A\r")
            await wait_text("Transient failure recovered")
            await send("/failure")
            assert not cancellations
            await send("\x1b\r")
            await send("q")
            await send("n")
            assert not cancellations
            await send("qy")
            await send("\x03")
            assert cancellations == [True]
            dashboard.finish(130)
            assert "Interrupted" in await refresh()
            keys.send_text("q")
        finally:
            if dashboard.application.is_running:
                dashboard.application.exit()
            await asyncio.wait_for(task, timeout=5)


@pytest.mark.asyncio
async def test_dashboard_mouse_controls_work_during_slow_log_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reading = threading.Event()
    release = threading.Event()
    rendered = asyncio.Event()
    cancellations: list[bool] = []

    def slow_read(_path: Path) -> str:
        reading.set()
        release.wait(timeout=10)
        return "\n".join([f"Example log line {index}" for index in range(60)] + ["Example log output"])

    monkeypatch.setattr(EvalDashboard, "_tail", staticmethod(slow_read))
    with create_pipe_input() as keys:
        dashboard = EvalDashboard(
            tmp_path / "run.log", input=keys, output=_TerminalOutput(80), cancel=lambda: cancellations.append(True)
        )
        dashboard.application.after_render += lambda _app: rendered.set()
        task = asyncio.create_task(dashboard.application.run_async(handle_sigint=False))

        async def wait_text(text: str) -> str:
            async with asyncio.timeout(5):
                while True:
                    if dashboard.application.renderer.last_rendered_screen is not None:
                        screen = _screen_text(dashboard.application)
                        if text in screen:
                            return screen
                    rendered.clear()
                    await rendered.wait()

        def click(text: str) -> None:
            keys.send_text(_mouse_sequence(dashboard.application, text))

        try:
            await wait_text("[Logs]")
            click("[Logs]")
            await wait_text("Loading logs")
            assert await asyncio.to_thread(reading.wait, 5)
            click("[Follow on]")
            await wait_text("[Follow off]")
            click("[Search]")
            await wait_text("I-search")
            keys.send_text("\x1b\r")
            await wait_text("[Cancel]")
            click("[Cancel]")
            await wait_text("[Continue]")
            assert not cancellations
            click("[Continue]")
            await wait_text("[Cancel]")
            click("[Cancel]")
            await wait_text("[Yes, cancel]")
            click("[Yes, cancel]")
            await wait_text("Cancel requested")
            assert cancellations == [True]
            click("[Follow off]")
            await wait_text("[Follow on]")
            release.set()
            await wait_text("Example log output")
            click("Example log output")
            keys.send_text(_mouse_sequence(dashboard.application, "Example log output", button=64))
            await wait_text("[Follow off]")
            assert dashboard.application.layout.has_focus(dashboard._details)
            dashboard.finish(0)
            await wait_text("[Close]")
            click("[Close]")
            await asyncio.wait_for(task, timeout=5)
        finally:
            release.set()
            if dashboard.application.is_running:
                dashboard.application.exit()
            await asyncio.wait_for(task, timeout=5)


@pytest.mark.parametrize("mode", ["dumb", "stderr", "redirected", "tty-selector"])
def test_dashboard_opens_through_hogli_with_redirected_streams(tmp_path: Path, mode: str) -> None:
    runner = (
        "from pathlib import Path; "
        "from products.posthog_ai.eval_harness.harness import __main__ as harness; "
        "create = harness.RunTranscript.create; "
        f"harness.RunTranscript.create = lambda: create(Path({str(tmp_path)!r})); "
        "harness._run = lambda *args, **kwargs: 0; "
        f"raise SystemExit(harness.main({[] if mode == 'stderr' else ['--tui']!r}))"
    )
    if mode == "tty-selector":
        runner = (
            dedent("""
            import errno
            import os
            import selectors
            import stat

            class NoTerminalSelector(selectors.DefaultSelector):
                def register(self, fileobj, events, data=None):
                    fd = fileobj if isinstance(fileobj, int) else fileobj.fileno()
                    if stat.S_ISCHR(os.fstat(fd).st_mode):
                        raise OSError(errno.EINVAL, "Invalid argument")
                    return super().register(fileobj, events, data)

            selectors.DefaultSelector = NoTerminalSelector
        """)
            + runner
        )
    launcher = (
        "import os, sys; "
        "from hogli.command_types import _run; "
        "terminal = os.dup(0); "
        "null = os.open(os.devnull, os.O_RDWR); "
        f"[os.dup2(null, fd) for fd in {([0, 1, 2] if mode in {'redirected', 'tty-selector'} else [2])!r}]; "
        "_run([sys.executable, '-c', sys.argv[1]])"
    )
    environment = dict(os.environ, TERM="dumb" if mode == "dumb" else "xterm-256color")
    environment.pop("CI", None)
    with pexpect.spawn(
        sys.executable, ["-c", launcher, runner], env=environment, encoding="utf-8", timeout=20
    ) as child:
        child.expect("Results ready")
        child.send("q")
        child.expect(pexpect.EOF)
    assert child.exitstatus == 0
    transcript = next(path for path in tmp_path.glob("*.log") if not path.is_symlink())
    text = transcript.read_text()
    assert "\x1b" not in text
    assert text.splitlines()[-1] == str(transcript)


@pytest.mark.parametrize("phase", ["startup", "runtime"])
def test_forced_dashboard_reports_render_failure_and_stops_the_run(tmp_path: Path, phase: str) -> None:
    program = dedent("""
        import sys
        import threading
        from pathlib import Path
        from products.posthog_ai.eval_harness.harness import __main__ as harness
        from products.posthog_ai.eval_harness.harness.dashboard import EvalDashboard

        root, phase = Path(sys.argv[1]), sys.argv[2]
        create = harness.RunTranscript.create
        harness.RunTranscript.create = lambda: create(root)

        def fail():
            raise RuntimeError("Example terminal render failure")

        def run(*args, dashboard, **kwargs):
            (root / "started").touch()
            dashboard._refresh = fail
            dashboard.application.invalidate()
            try:
                threading.Event().wait(timeout=10)
            finally:
                (root / "cleaned-up").touch()
            return 0

        if phase == "startup":
            EvalDashboard._refresh = lambda self: fail()
        harness._run = run
        raise SystemExit(harness.main(["--tui"]))
    """)
    environment = dict(os.environ, TERM="xterm-256color")
    with pexpect.spawn(
        sys.executable, ["-c", program, str(tmp_path), phase], env=environment, encoding="utf-8", timeout=20
    ) as child:
        child.expect(pexpect.EOF)
        output = child.before
    assert child.exitstatus == 1
    assert output.count("Example terminal render failure") == 1
    assert (tmp_path / "started").exists() is (phase == "runtime")
    assert (tmp_path / "cleaned-up").exists() is (phase == "runtime")
    transcript = next(path for path in tmp_path.glob("*.log") if not path.is_symlink())
    saved = transcript.read_text()
    assert "Traceback" in saved
    assert "RuntimeError: Example terminal render failure" in saved
    assert "\x1b" not in saved
    assert output.splitlines()[-1] == saved.splitlines()[-1] == str(transcript)
