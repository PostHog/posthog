from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

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
