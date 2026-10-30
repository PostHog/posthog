from __future__ import annotations

import os
import sys
import asyncio
import subprocess
from collections.abc import Awaitable, Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Literal, cast
from uuid import UUID

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import requests
from parameterized import parameterized

from products.posthog_ai.eval_harness import runner
from products.posthog_ai.eval_harness.config import AgentArtifacts, SandboxedEvalCase
from products.posthog_ai.eval_harness.engines.types import AggregateScore, EvalSummary
from products.posthog_ai.eval_harness.harness import lifecycle
from products.posthog_ai.eval_harness.harness.cli import SkillDelivery, parse_args
from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.harness.discovery import EvalSuite
from products.posthog_ai.eval_harness.harness.lifecycle import SandboxedEvalHarness
from products.posthog_ai.eval_harness.harness.live_server import EvalLiveServer
from products.posthog_ai.eval_harness.harness.providers import (
    DockerProviderStrategy,
    ModalProviderStrategy,
    SandboxProviderStrategy,
)
from products.posthog_ai.eval_harness.harness.reporting import ProgressReporter
from products.tasks.backend.facade.agents import (
    CustomPromptSandboxContext,
    MultiTurnSession,
    TurnPollResult,
    TurnPollTimeout,
)
from products.tasks.backend.facade.contracts import AgentTaskRunDTO
from products.tasks.backend.logic.services import custom_prompt_internals
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext
from products.tasks.backend.temporal.process_task.utils import mcp_exec_skills_env_vars


class _FakeWorkflowHandle:
    def __init__(self, *, complete_on_signal: bool, complete_on_cancel: bool = False) -> None:
        self.complete_on_signal = complete_on_signal
        self.complete_on_cancel = complete_on_cancel
        self.signal_received = asyncio.Event()
        self.terminal = asyncio.Event()
        self.signals: list[list[str | None]] = []
        self.cancelled = False

    async def signal(self, _signal: object, *, args: list[str | None]) -> None:
        self.signals.append(args)
        self.signal_received.set()
        if self.complete_on_signal:
            self.terminal.set()

    async def result(self) -> None:
        await self.terminal.wait()

    async def cancel(self) -> None:
        self.cancelled = True
        if self.complete_on_cancel:
            self.terminal.set()


class _Provider(SandboxProviderStrategy):
    name = "docker"
    default_max_sandboxes = 1

    def __init__(self) -> None:
        super().__init__()
        self.cleaned_task_ids: list[str] = []

    def preflight(self) -> None:
        return None

    def settings_overrides(self) -> dict[str, object]:
        return {}

    def cleanup_case(self, task_id: str) -> None:
        self.cleaned_task_ids.append(task_id)


_TASK_ID = UUID("00000000-0000-0000-0000-000000000001")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "system_prompt",
    [None, {"type": "preset", "preset": "claude_code", "append": "Test surface instructions"}],
)
async def test_surface_prompt_reaches_task_run_state(
    monkeypatch: pytest.MonkeyPatch, system_prompt: dict[str, str] | None
) -> None:
    task = MagicMock(id=_TASK_ID, team_id=25)
    task.latest_run = MagicMock(id=UUID("00000000-0000-0000-0000-000000000002"))
    create = MagicMock(return_value=task)
    monkeypatch.setattr(custom_prompt_internals.Team.objects, "get", MagicMock(return_value=MagicMock(id=25)))
    monkeypatch.setattr(custom_prompt_internals.Task, "create_and_run", create)

    await runner.create_task_and_trigger(
        "prompt", CustomPromptSandboxContext(team_id=25, user_id=26, system_prompt=system_prompt)
    )

    assert create.call_args.kwargs["extra_run_state"] == (
        {"systemPrompt": system_prompt} if system_prompt is not None else {}
    )


def _patch_runner_boundaries(monkeypatch: pytest.MonkeyPatch, handle: _FakeWorkflowHandle, poll: AsyncMock) -> None:
    task_run = AgentTaskRunDTO(
        task_id=_TASK_ID,
        run_id=UUID("00000000-0000-0000-0000-000000000002"),
        team_id=25,
        workflow_id="eval-task-workflow",
    )
    client = SimpleNamespace(get_workflow_handle=lambda _workflow_id: handle)
    monkeypatch.setattr(runner, "create_task_and_trigger", AsyncMock(return_value=task_run))
    monkeypatch.setattr(runner, "async_connect", AsyncMock(return_value=client))
    monkeypatch.setattr(runner, "poll_for_turn", poll)


def test_eval_live_server_routes_event_ingest_through_asgi() -> None:
    with (
        patch("posthog.asgi._ensure_post_fork_init"),
        patch("posthog.utils.initialize_self_capture_api_token", new=AsyncMock()),
    ):
        server = EvalLiveServer(port=0)
        try:
            response = requests.post(
                f"{server.url}/api/projects/25/tasks/task-id/runs/run-id/event_stream/",
                timeout=5,
            )
        finally:
            server.stop()

    assert response.status_code == 401
    assert response.json() == {"error": "Missing authorization bearer token"}


def test_setup_django_disables_self_capture_before_settings_load() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from products.posthog_ai.eval_harness.harness.django_env import setup_django\n"
                "setup_django()\n"
                "from django.conf import settings\n"
                "assert settings.SELF_CAPTURE is False\n"
            ),
        ],
        cwd=Path(__file__).resolve().parents[4],
        env={**os.environ, "SELF_CAPTURE": "1"},
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr


@parameterized.expand([(0,), (-1,)])
def test_parse_args_rejects_non_positive_case_timeout(case_timeout: int) -> None:
    with pytest.raises(SystemExit) as error:
        parse_args(["--case-timeout", str(case_timeout)])

    assert error.value.code == 2


@parameterized.expand(
    [
        ("local", {}, 1),
        ("coder", {"CODER": "true"}, 4),
        ("ci", {"CI": ""}, 4),
    ]
)
def test_parse_args_resolves_team_setup_concurrency(
    _environment_name: str, environment: dict[str, str], expected_concurrency: int
) -> None:
    with patch.dict(os.environ, environment, clear=True):
        options = parse_args([])

    assert options.team_setup_concurrency == expected_concurrency


@pytest.mark.parametrize(
    "outcome, fail_under, score, expected_exit_code",
    [
        pytest.param("case_error", None, 1.0, 1, id="case_error_without_gate"),
        pytest.param("engine_error", None, 1.0, 1, id="engine_error_without_gate"),
        pytest.param("both_errors", 0.5, 1.0, 1, id="errors_with_passing_gate"),
        pytest.param("case_error", 1.0, 1.0, 1, id="case_error_with_perfect_score"),
        pytest.param("crash", None, 1.0, 1, id="suite_crash"),
        pytest.param("ok", None, 0.0, 0, id="low_score_without_gate"),
        pytest.param("ok", 0.5, 0.5, 0, id="score_meets_gate"),
        pytest.param("ok", 0.5, 0.0, 1, id="score_below_gate"),
        pytest.param("ok", 0.5, None, 1, id="no_scores_with_gate"),
        pytest.param("timeout", None, 0.0, 0, id="timeout_without_gate"),
        pytest.param("timeout", 0.5, 0.0, 1, id="timeout_below_gate"),
        pytest.param("check", None, None, 0, id="configuration_check_only"),
    ],
)
def test_eval_run_exit_status(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    outcome: Literal["ok", "case_error", "engine_error", "both_errors", "timeout", "crash", "check"],
    fail_under: float | None,
    score: float | None,
    expected_exit_code: int,
) -> None:
    monkeypatch.delenv("EXPORT_EVAL_RESULTS", raising=False)

    async def suite(ctx: EvalContext) -> None:
        assert outcome != "check", "Configuration checks must not execute cases"
        if outcome == "crash":
            raise RuntimeError("Synthetic suite failure")
        await ctx.reporter.case_done("experiment", "completed-case", duration_seconds=1.0)
        if outcome in {"case_error", "both_errors", "timeout"}:
            await ctx.reporter.case_done(
                "experiment",
                "failed-case",
                duration_seconds=1.0,
                status="timeout" if outcome == "timeout" else "error",
            )
        await ctx.reporter.record_summary(
            "experiment",
            EvalSummary(
                engine_name="Braintrust",
                experiment_name="experiment",
                scores={"score": AggregateScore("score", score)} if score is not None else {},
            ),
            error_count=1 if outcome in {"engine_error", "both_errors"} else 0,
        )

    monkeypatch.setattr(
        lifecycle,
        "discover_suites",
        lambda _selectors: [EvalSuite(domain="test", module_name="exit_status", fn_name="suite", fn=suite)],
    )
    monkeypatch.setattr(lifecycle, "infra_union", lambda _kinds: frozenset())
    monkeypatch.setattr(lifecycle, "validate_eval_env", lambda *_args, **_kwargs: None)
    bootstrap = MagicMock()
    monkeypatch.setattr(SandboxedEvalHarness, "_bootstrap", bootstrap)
    args = [] if fail_under is None else ["--fail-under", str(fail_under)]
    if outcome == "check":
        args.append("--check")

    assert SandboxedEvalHarness(parse_args(args)).run() == expected_exit_code
    output = capsys.readouterr().out
    if outcome == "check":
        bootstrap.assert_not_called()
        assert "SUITE START" not in output
    else:
        assert f"Status: {'PASS' if expected_exit_code == 0 else 'FAIL'}" in output


def test_eval_run_rejects_overwriting_its_snapshot_input(tmp_path: Path) -> None:
    report = tmp_path / "results.json"
    report.write_text('{"saved": true}')
    harness = SandboxedEvalHarness(parse_args(["--skill-snapshot-report", str(report), "--results-file", str(report)]))

    with pytest.raises(lifecycle.PreflightError, match="must use different paths"):
        harness.run()

    assert report.read_text() == '{"saved": true}'


@pytest.mark.asyncio
@pytest.mark.parametrize("delivery", ["bundled", "exec"])
@pytest.mark.parametrize("origin", ["eval", "slack", None])
async def test_eval_run_preserves_bundled_skills_unless_exec_is_selected(
    delivery: SkillDelivery, origin: str | None
) -> None:
    harness = SandboxedEvalHarness(parse_args(["--skill-delivery", delivery]))
    environments: list[dict[str, str]] = []

    async def suite(ctx: EvalContext) -> None:
        task_context = TaskProcessingContext(
            task_id="task-id",
            run_id="run-id",
            team_id=1,
            team_uuid="team-1",
            organization_id="org-1",
            github_integration_id=None,
            repository=None,
            distinct_id="user-1",
            state={"interaction_origin": origin},
        )
        environments.append(await asyncio.to_thread(mcp_exec_skills_env_vars, task_context))

    results = await harness._run_suites(
        [EvalSuite(domain="test", module_name="skill_delivery", fn_name="suite", fn=suite)],
        frozenset(),
        ProgressReporter(total_suites=1),
    )

    assert results[0].status == "passed", results[0].error
    expected = {"POSTHOG_CODE_DISABLE_BUNDLED_SKILLS": "1"} if delivery == "exec" and origin else {}
    assert environments == [expected]


@pytest.mark.asyncio
@pytest.mark.parametrize("reporting_error", [None, BrokenPipeError("closed output")])
@pytest.mark.parametrize("budget", [None, 900, 20])
async def test_success_waits_for_workflow_cleanup_before_returning(
    monkeypatch: pytest.MonkeyPatch, budget: int | None, reporting_error: Exception | None
) -> None:
    monkeypatch.setattr(runner, "time", SimpleNamespace(monotonic=lambda: 1000.0))
    handle = _FakeWorkflowHandle(complete_on_signal=False)
    provider = _Provider()
    poll = AsyncMock(
        return_value=TurnPollResult(
            last_message="done", full_log='{"notification": {}}', total_lines=0, printed_lines=0
        )
    )
    _patch_runner_boundaries(monkeypatch, handle, poll)

    cleanup_started = asyncio.Event()

    async def on_cleanup() -> None:
        cleanup_started.set()
        if reporting_error is not None:
            raise reporting_error

    case_task = asyncio.create_task(
        runner.run_eval_case(
            SandboxedEvalCase(name="case", prompt="prompt"),
            MagicMock(),
            provider=provider,
            on_cleanup=on_cleanup,
            timeout_seconds=budget,
        )
    )
    await asyncio.wait_for(handle.signal_received.wait(), timeout=1)
    assert cleanup_started.is_set()

    assert not case_task.done()
    handle.terminal.set()
    result = await asyncio.wait_for(case_task, timeout=1)

    assert result.artifacts.exit_code == 0
    assert handle.signals == [["completed", None]]
    assert provider.cleaned_task_ids == [str(_TASK_ID)]

    expected = 1000 + budget - min(120, budget / 4) if budget is not None else None
    assert poll.await_args is not None
    assert poll.await_args.kwargs["poll_deadline"] == expected
    assert poll.await_args.kwargs["workflow_handle"] is handle


@pytest.mark.asyncio
@pytest.mark.parametrize("reporting_error", [None, BrokenPipeError("closed output")])
async def test_poll_failure_is_preserved_after_workflow_cleanup(
    monkeypatch: pytest.MonkeyPatch, reporting_error: Exception | None
) -> None:
    handle = _FakeWorkflowHandle(complete_on_signal=True)
    provider = _Provider()
    _patch_runner_boundaries(monkeypatch, handle, AsyncMock(side_effect=RuntimeError("poll failed")))

    with pytest.raises(RuntimeError, match="poll failed"):
        await runner.run_eval_case(
            SandboxedEvalCase(name="case", prompt="prompt"),
            MagicMock(),
            provider=provider,
            on_cleanup=AsyncMock(side_effect=reporting_error),
        )

    assert handle.signals[0][0] == "failed"
    assert provider.cleaned_task_ids == [str(_TASK_ID)]


@pytest.mark.asyncio
@pytest.mark.parametrize("poll_failed", [False, True])
async def test_cancellation_during_progress_waits_for_workflow_cleanup(
    monkeypatch: pytest.MonkeyPatch, poll_failed: bool
) -> None:
    handle = _FakeWorkflowHandle(complete_on_signal=False)
    provider = _Provider()
    _patch_runner_boundaries(
        monkeypatch,
        handle,
        AsyncMock(
            side_effect=RuntimeError("poll failed") if poll_failed else None,
            return_value=TurnPollResult(last_message="done", full_log="", total_lines=0, printed_lines=0),
        ),
    )
    progress_started = asyncio.Event()
    progress_release = asyncio.Event()

    async def on_cleanup() -> None:
        progress_started.set()
        await progress_release.wait()

    case_task = asyncio.create_task(
        runner.run_eval_case(
            SandboxedEvalCase(name="case", prompt="prompt"),
            MagicMock(),
            provider=provider,
            on_cleanup=on_cleanup,
        )
    )
    try:
        await asyncio.wait_for(progress_started.wait(), timeout=1)
        case_task.cancel()
        await asyncio.wait_for(handle.signal_received.wait(), timeout=1)
        assert not case_task.done()
        handle.terminal.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(case_task, timeout=1)
    finally:
        progress_release.set()
        handle.terminal.set()
    assert handle.signals[0][0] == ("failed" if poll_failed else "completed")
    assert provider.cleaned_task_ids == [str(_TASK_ID)]


@pytest.mark.asyncio
@pytest.mark.parametrize("reporting_error", [None, BrokenPipeError("closed output")])
async def test_cancellation_finishes_workflow_before_propagating(
    monkeypatch: pytest.MonkeyPatch, reporting_error: Exception | None
) -> None:
    poll_started = asyncio.Event()
    never_finishes = asyncio.Event()

    async def poll_for_turn(*_args: object, **_kwargs: object) -> None:
        poll_started.set()
        await never_finishes.wait()

    handle = _FakeWorkflowHandle(complete_on_signal=True)
    provider = _Provider()
    _patch_runner_boundaries(monkeypatch, handle, AsyncMock(side_effect=poll_for_turn))
    case_task = asyncio.create_task(
        runner.run_eval_case(
            SandboxedEvalCase(name="case", prompt="prompt"),
            MagicMock(),
            provider=provider,
            on_cleanup=AsyncMock(side_effect=reporting_error),
        )
    )
    await asyncio.wait_for(poll_started.wait(), timeout=1)

    case_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await case_task

    assert handle.signals[0][0] == "failed"
    assert provider.cleaned_task_ids == [str(_TASK_ID)]


@pytest.mark.asyncio
async def test_unconfirmed_success_is_an_infrastructure_error(monkeypatch: pytest.MonkeyPatch) -> None:
    handle = _FakeWorkflowHandle(complete_on_signal=False)
    provider = _Provider()
    _patch_runner_boundaries(
        monkeypatch,
        handle,
        AsyncMock(
            return_value=TurnPollResult(
                last_message="done", full_log='{"notification": {}}', total_lines=0, printed_lines=0
            )
        ),
    )
    monkeypatch.setattr(runner, "WORKFLOW_COMPLETION_GRACE_SECONDS", 0.01)
    monkeypatch.setattr(runner, "WORKFLOW_CANCELLATION_GRACE_SECONDS", 0.01)

    with pytest.raises(runner.WorkflowCleanupError, match="cleanup could not be confirmed"):
        await runner.run_eval_case(
            SandboxedEvalCase(name="case", prompt="prompt"),
            MagicMock(),
            provider=provider,
        )

    assert handle.cancelled
    assert provider.cleaned_task_ids == [str(_TASK_ID)]


def test_modal_cleanup_case_terminates_only_the_task_sandboxes(monkeypatch: pytest.MonkeyPatch) -> None:
    sandbox = SimpleNamespace(object_id="sandbox-id", terminate=MagicMock())
    sandbox_list = MagicMock(return_value=[sandbox])
    modal = SimpleNamespace(
        App=SimpleNamespace(lookup=MagicMock(return_value=SimpleNamespace(app_id="app-id"))),
        Sandbox=SimpleNamespace(list=sandbox_list),
    )
    monkeypatch.setitem(sys.modules, "modal", modal)
    provider = ModalProviderStrategy()
    provider._sandbox_app_name = "eval-app"

    provider.cleanup_case("task-id")

    sandbox_list.assert_called_once_with(app_id="app-id", tags={"task_id": "task-id"})
    sandbox.terminate.assert_called_once_with()


def _docker_provider() -> SandboxProviderStrategy:
    return DockerProviderStrategy(keep_containers=False)


def _modal_provider() -> SandboxProviderStrategy:
    provider = ModalProviderStrategy()
    provider._tunnels = cast(Any, SimpleNamespace(url_for=lambda name: f"https://{name}.funnel.example.com"))
    return provider


@parameterized.expand(
    [
        ("docker", _docker_provider, "http://localhost:18080", "http://host.docker.internal:18080"),
        ("modal", _modal_provider, "https://gateway.funnel.example.com", "https://gateway.funnel.example.com"),
    ]
)
def test_provider_routes_model_calls_to_a_gateway_the_host_worker_can_mint_through(
    _name: str, build: Callable[[], SandboxProviderStrategy], gateway_url: str, fallback_url: str
) -> None:
    overrides = build().settings_overrides()

    assert overrides["SANDBOX_AI_GATEWAY_URL"] == gateway_url
    assert overrides["SANDBOX_LLM_GATEWAY_URL"] == fallback_url


class TestAgentRunFailureDetection:
    # An agent-server failure reaches the log as a session error, and the workflow still finishes
    # cleanly afterwards. Miss it and a run where no agent ever spoke reports exit_code_zero=1 with
    # zeros on every outcome scorer, which reads as a model regression.
    def test_a_session_error_makes_the_run_a_failure(self) -> None:
        log = "\n".join(
            [
                '{"notification": {"method": "session/update", "params": {"update": '
                '{"sessionUpdate": "error", "errorType": "agent_error", "message": "403 model_gate"}}}}',
            ]
        )
        artifacts = runner._parse_artifacts_from_log(log, duration_seconds=1.0, agent_finished=True)
        assert artifacts.exit_code == 1
        assert "403 model_gate" in artifacts.stderr

    # A provider 403 lands on the terminal `_posthog/error` channel, which sets the non-zero exit
    # code but leaves `stderr` empty. Reading `stderr` to spot the infra failure would score this
    # run at zero on every outcome scorer instead of dropping it from the aggregates.
    def test_a_terminal_posthog_error_with_no_tool_call_is_infrastructure(self) -> None:
        log = '{"notification": {"method": "_posthog/error", "params": {"message": "403 model_gate"}}}'
        artifacts = runner._parse_artifacts_from_log(log, duration_seconds=1.0, agent_finished=True)
        assert artifacts.exit_code == 1
        assert artifacts.tool_call_count == 0
        assert runner.agent_never_ran(artifacts) is True

    @parameterized.expand(
        [
            ("no work behind the error", "403 model_gate", 0, True),
            ("errored after doing work", "stream terminated", 3, False),
            ("clean run", "", 2, False),
            ("clean run with no tool calls", "", 0, False),
        ]
    )
    def test_only_a_run_that_did_nothing_counts_as_infrastructure(
        self, _name: str, stderr: str, tool_call_count: int, expected: bool
    ) -> None:
        artifacts = AgentArtifacts(exit_code=1 if stderr else 0, stderr=stderr, tool_call_count=tool_call_count)
        assert runner.agent_never_ran(artifacts) is expected


class TestSliceTurnLogs:
    def test_slices_by_turn_line_marks(self) -> None:
        log = "\n".join(f'{{"line": {i}}}' for i in range(5))
        assert runner._slice_turn_logs(log, [2, 5]) == [
            '{"line": 0}\n{"line": 1}',
            '{"line": 2}\n{"line": 3}\n{"line": 4}',
        ]

    def test_single_turn_spans_the_whole_log(self) -> None:
        log = "\n".join(f'{{"line": {i}}}' for i in range(3))
        assert runner._slice_turn_logs(log, [3]) == [log]

    def test_marks_past_the_line_count_disable_slicing(self) -> None:
        log = "\n".join(f'{{"line": {i}}}' for i in range(3))
        assert runner._slice_turn_logs(log, [2, 9]) is None

    def test_a_malformed_line_disables_slicing(self) -> None:
        assert runner._slice_turn_logs('{"line": 0}\nnot json\n{"line": 1}', [1, 3]) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("initial_failure", [False, True])
@pytest.mark.parametrize("cleanup_cancelled", [False, True])
async def test_multi_turn_timeout_retains_cleanup_state(
    monkeypatch: pytest.MonkeyPatch, initial_failure: bool, cleanup_cancelled: bool
) -> None:
    handle = _FakeWorkflowHandle(complete_on_signal=not cleanup_cancelled)
    provider = _Provider()
    error = TurnPollTimeout(
        "Poll budget expired",
        stage="no_turn_output",
        elapsed=10,
        stale_seconds=10,
        total_lines=0,
        turn_relevant_lines=0,
    )
    monkeypatch.setattr(runner, "time", SimpleNamespace(monotonic=lambda: 1000.0))
    monkeypatch.setattr(
        runner, "async_connect", AsyncMock(return_value=SimpleNamespace(get_workflow_handle=lambda _: handle))
    )
    task_run = MagicMock(task_id=_TASK_ID)
    session = MagicMock(task=SimpleNamespace(id=_TASK_ID), workflow_handle=handle, log_lines_seen=0)
    session.send_followup_raw = AsyncMock(side_effect=error)

    async def start(**kwargs: object) -> tuple[MultiTurnSession, str]:
        assert kwargs["poll_deadline"] == 1780.0
        callback = cast(Callable[[object], Awaitable[None]], kwargs["on_task_run_created"])
        await callback(task_run)
        if initial_failure:
            raise error
        return session, "done"

    monkeypatch.setattr(runner.MultiTurnSession, "start_raw", start)
    diagnostics: dict[str, object] = {}
    case_task = asyncio.create_task(
        runner.run_eval_case(
            SandboxedEvalCase(name="case", prompt="prompt", followups=["followup"]),
            MagicMock(),
            provider=provider,
            timeout_seconds=900,
            on_poll_timeout=lambda error: diagnostics.update(error.diagnostics()),
        )
    )
    await asyncio.wait_for(handle.signal_received.wait(), timeout=1)
    assert diagnostics == error.diagnostics()
    if cleanup_cancelled:
        case_task.cancel()
        handle.terminal.set()
    with pytest.raises(asyncio.CancelledError if cleanup_cancelled else TurnPollTimeout):
        await case_task
    assert handle.signals[0][0] == "failed"
    assert provider.cleaned_task_ids == [str(_TASK_ID)]
