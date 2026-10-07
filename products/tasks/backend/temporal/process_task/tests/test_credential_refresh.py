import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock

from temporalio.exceptions import ActivityError, CancelledError

from products.tasks.backend.temporal.process_task import credential_refresh as credential_refresh_module
from products.tasks.backend.temporal.process_task.activities.refresh_sandbox_credentials import (
    RefreshSandboxCredentialsOutput,
)
from products.tasks.backend.temporal.process_task.credential_refresh import (
    CredentialRefreshExitReason,
    run_credential_refresh_loop,
)


class TestRunCredentialRefreshLoop:
    def _patch_workflow(self, monkeypatch, execute_activity):
        monkeypatch.setattr(credential_refresh_module.workflow, "execute_activity", execute_activity)
        monkeypatch.setattr(credential_refresh_module.workflow, "sleep", AsyncMock())
        monkeypatch.setattr(credential_refresh_module.workflow, "logger", MagicMock())

    @pytest.mark.parametrize("patched", [True, False])
    async def test_cancel_during_activity_propagates_only_for_patched_histories(
        self, monkeypatch: pytest.MonkeyPatch, patched: bool
    ) -> None:
        activity_started = asyncio.Event()
        cancelled = ActivityError(
            "Activity cancelled",
            scheduled_event_id=1,
            started_event_id=2,
            identity="test-worker",
            activity_type="refresh_sandbox_credentials",
            activity_id="refresh",
            retry_state=None,
        )
        cancelled.__cause__ = CancelledError()

        async def blocked_activity(*args: object, **kwargs: object) -> RefreshSandboxCredentialsOutput:
            activity_started.set()
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                raise cancelled
            raise AssertionError("Activity must be cancelled")

        execute_activity = AsyncMock(side_effect=blocked_activity)
        self._patch_workflow(monkeypatch, execute_activity)
        patch = MagicMock(return_value=patched)
        monkeypatch.setattr(credential_refresh_module.workflow, "patched", patch)
        task = asyncio.create_task(run_credential_refresh_loop(MagicMock(), "sb-1"))
        await activity_started.wait()
        execute_activity.side_effect = None
        execute_activity.return_value = RefreshSandboxCredentialsOutput(
            next_refresh_seconds=1.0, refreshed_kinds=[], sandbox_gone=True
        )
        task.cancel()

        if patched:
            with pytest.raises(ActivityError) as error:
                await task
            assert error.value is cancelled
            assert execute_activity.await_count == 1
        else:
            assert await task == CredentialRefreshExitReason.SANDBOX_GONE
            assert execute_activity.await_count == 2
        patch.assert_called_once_with("tasks-credential-refresh-propagate-cancel")

    async def test_non_cancellation_failure_retries(self, monkeypatch: pytest.MonkeyPatch) -> None:
        execute_activity = AsyncMock(
            side_effect=[
                RuntimeError("Refresh temporarily unavailable"),
                RefreshSandboxCredentialsOutput(next_refresh_seconds=1.0, refreshed_kinds=[], sandbox_gone=True),
            ]
        )
        self._patch_workflow(monkeypatch, execute_activity)

        assert await run_credential_refresh_loop(MagicMock(), "sb-1") == CredentialRefreshExitReason.SANDBOX_GONE
        assert execute_activity.await_count == 2

    async def test_orphaned_kinds_are_excluded_next_cycle_and_loop_stops(self, monkeypatch):
        execute_activity = AsyncMock(
            side_effect=[
                RefreshSandboxCredentialsOutput(
                    next_refresh_seconds=1.0, refreshed_kinds=[], orphaned_kinds=["github"]
                ),
                RefreshSandboxCredentialsOutput(next_refresh_seconds=1.0, refreshed_kinds=[], no_credentials_left=True),
            ]
        )
        self._patch_workflow(monkeypatch, execute_activity)

        exit_reason = await run_credential_refresh_loop(MagicMock(), "sb-1")

        assert exit_reason == CredentialRefreshExitReason.CREDENTIALS_UNAVAILABLE
        assert execute_activity.await_count == 2
        second_input = execute_activity.await_args_list[1].args[1]
        assert second_input.exclude_kinds == ["github"]

    async def test_task_gone_stops_loop(self, monkeypatch):
        # Without this exit the loop would spin forever against rows a team deletion removed.
        execute_activity = AsyncMock(
            side_effect=[
                RefreshSandboxCredentialsOutput(next_refresh_seconds=1.0, refreshed_kinds=[], task_gone=True),
            ]
        )
        self._patch_workflow(monkeypatch, execute_activity)

        exit_reason = await run_credential_refresh_loop(MagicMock(), "sb-1")

        assert exit_reason == CredentialRefreshExitReason.TASK_GONE
        assert execute_activity.await_count == 1

    async def test_sandbox_gone_still_wins_over_orphaned_kinds(self, monkeypatch):
        execute_activity = AsyncMock(
            side_effect=[
                RefreshSandboxCredentialsOutput(
                    next_refresh_seconds=1.0,
                    refreshed_kinds=[],
                    sandbox_gone=True,
                    orphaned_kinds=["github"],
                    no_credentials_left=True,
                    sandbox_exit_reason="timed out",
                ),
            ]
        )
        self._patch_workflow(monkeypatch, execute_activity)
        on_sandbox_gone = MagicMock()

        exit_reason = await run_credential_refresh_loop(MagicMock(), "sb-1", on_sandbox_gone=on_sandbox_gone)

        assert exit_reason == CredentialRefreshExitReason.SANDBOX_GONE
        on_sandbox_gone.assert_called_once_with("timed out")
