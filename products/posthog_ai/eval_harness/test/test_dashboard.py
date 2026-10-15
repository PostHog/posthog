from __future__ import annotations

import os
import sys
import asyncio
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
        task = asyncio.create_task(dashboard.application.run_async(handle_sigint=False))

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
            assert "start example service" in await refresh()
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
            screen = await send("\x1b[B\r")
            assert "Trial answer" in screen
            assert "Setup retries: 1" in screen
            assert "trial log contents" in await send("l")
            assert "Transient failure recovered" in await send("\x1b[A\r")
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


@pytest.mark.parametrize("mode", ["dumb", "stderr", "redirected"])
def test_dashboard_opens_through_hogli_with_redirected_streams(tmp_path: Path, mode: str) -> None:
    runner = (
        "from pathlib import Path; "
        "from products.posthog_ai.eval_harness.harness import __main__ as harness; "
        "create = harness.RunTranscript.create; "
        f"harness.RunTranscript.create = lambda: create(Path({str(tmp_path)!r})); "
        "harness._run = lambda *args, **kwargs: 0; "
        f"raise SystemExit(harness.main({[] if mode == 'stderr' else ['--tui']!r}))"
    )
    launcher = (
        "import os, sys; "
        "from hogli.command_types import _run; "
        "terminal = os.dup(0); "
        "null = os.open(os.devnull, os.O_RDWR); "
        f"[os.dup2(null, fd) for fd in {([0, 1, 2] if mode == 'redirected' else [2])!r}]; "
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
