from __future__ import annotations

import os
import sys
import asyncio
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import requests
from parameterized import parameterized

from products.posthog_ai.eval_harness import runner
from products.posthog_ai.eval_harness.config import SandboxedEvalCase
from products.posthog_ai.eval_harness.harness.cli import parse_args
from products.posthog_ai.eval_harness.harness.live_server import EvalLiveServer
from products.posthog_ai.eval_harness.harness.providers import ModalProviderStrategy, SandboxProviderStrategy


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


class _TaskRun:
    id = "run-id"

    def get_workflow_id(self, task_id: str, run_id: str) -> str:
        return f"{task_id}-{run_id}"


def _patch_runner_boundaries(monkeypatch: pytest.MonkeyPatch, handle: _FakeWorkflowHandle, poll: AsyncMock) -> None:
    task = SimpleNamespace(id="task-id")
    task_run = _TaskRun()
    client = SimpleNamespace(get_workflow_handle=lambda _workflow_id: handle)
    monkeypatch.setattr(runner, "create_task_and_trigger", AsyncMock(return_value=(task, task_run)))
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


@pytest.mark.asyncio
async def test_success_waits_for_workflow_cleanup_before_returning(monkeypatch: pytest.MonkeyPatch) -> None:
    handle = _FakeWorkflowHandle(complete_on_signal=False)
    provider = _Provider()
    _patch_runner_boundaries(
        monkeypatch,
        handle,
        AsyncMock(return_value=("done", '{"notification": {}}', None, None)),
    )

    case_task = asyncio.create_task(
        runner.run_eval_case(
            SandboxedEvalCase(name="case", prompt="prompt"),
            MagicMock(),
            provider=provider,
        )
    )
    await asyncio.wait_for(handle.signal_received.wait(), timeout=1)

    assert not case_task.done()
    handle.terminal.set()
    result = await asyncio.wait_for(case_task, timeout=1)

    assert result.artifacts.exit_code == 0
    assert handle.signals == [["completed", None]]
    assert provider.cleaned_task_ids == ["task-id"]


@pytest.mark.asyncio
async def test_poll_failure_is_preserved_after_workflow_cleanup(monkeypatch: pytest.MonkeyPatch) -> None:
    handle = _FakeWorkflowHandle(complete_on_signal=True)
    provider = _Provider()
    _patch_runner_boundaries(monkeypatch, handle, AsyncMock(side_effect=RuntimeError("poll failed")))

    with pytest.raises(RuntimeError, match="poll failed"):
        await runner.run_eval_case(
            SandboxedEvalCase(name="case", prompt="prompt"),
            MagicMock(),
            provider=provider,
        )

    assert handle.signals[0][0] == "failed"
    assert provider.cleaned_task_ids == ["task-id"]


@pytest.mark.asyncio
async def test_cancellation_finishes_workflow_before_propagating(monkeypatch: pytest.MonkeyPatch) -> None:
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
        )
    )
    await asyncio.wait_for(poll_started.wait(), timeout=1)

    case_task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await case_task

    assert handle.signals[0][0] == "failed"
    assert provider.cleaned_task_ids == ["task-id"]


@pytest.mark.asyncio
async def test_unconfirmed_success_is_an_infrastructure_error(monkeypatch: pytest.MonkeyPatch) -> None:
    handle = _FakeWorkflowHandle(complete_on_signal=False)
    provider = _Provider()
    _patch_runner_boundaries(
        monkeypatch,
        handle,
        AsyncMock(return_value=("done", '{"notification": {}}', None, None)),
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
    assert provider.cleaned_task_ids == ["task-id"]


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
