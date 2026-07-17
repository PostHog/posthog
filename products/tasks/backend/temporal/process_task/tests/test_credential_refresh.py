from unittest.mock import AsyncMock, MagicMock

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

    async def test_sandbox_gone_still_wins_over_orphaned_kinds(self, monkeypatch):
        execute_activity = AsyncMock(
            side_effect=[
                RefreshSandboxCredentialsOutput(
                    next_refresh_seconds=1.0,
                    refreshed_kinds=[],
                    sandbox_gone=True,
                    orphaned_kinds=["github"],
                    no_credentials_left=True,
                ),
            ]
        )
        self._patch_workflow(monkeypatch, execute_activity)

        exit_reason = await run_credential_refresh_loop(MagicMock(), "sb-1")

        assert exit_reason == CredentialRefreshExitReason.SANDBOX_GONE
