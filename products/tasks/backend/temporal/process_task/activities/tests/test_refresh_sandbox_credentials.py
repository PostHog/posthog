import pytest
from unittest.mock import MagicMock, patch

from asgiref.sync import async_to_sync

from products.tasks.backend.exceptions import SandboxExecutionError, SandboxNotFoundError, SandboxNotRunningError
from products.tasks.backend.logic.services.sandbox import ExecutionResult
from products.tasks.backend.temporal.process_task.activities.refresh_sandbox_credentials import (
    RefreshSandboxCredentialsInput,
    refresh_sandbox_credentials,
)
from products.tasks.backend.temporal.process_task.sandbox_credentials import DEFAULT_REFRESH_INTERVAL_SECONDS


@pytest.mark.django_db(transaction=True)
class TestRefreshSandboxCredentialsActivity:
    @pytest.fixture
    def sandbox(self):
        fake = MagicMock()
        fake.is_running.return_value = True
        fake.execute.return_value = ExecutionResult(stdout="", stderr="", exit_code=0)
        fake.write_file.return_value = ExecutionResult(stdout="", stderr="", exit_code=0)
        return fake

    def test_refreshes_github_credentials_and_reports_interval(
        self, activity_environment, task_context, test_task, sandbox
    ):
        with (
            patch(
                "products.tasks.backend.temporal.process_task.activities.refresh_sandbox_credentials.Sandbox.get_by_id",
                return_value=sandbox,
            ),
            patch(
                "products.tasks.backend.temporal.process_task.sandbox_credentials.get_sandbox_github_token",
                return_value="ghs_fresh",
            ),
            patch(
                "products.tasks.backend.temporal.process_task.activities.refresh_sandbox_credentials.track_event"
            ) as track_event,
        ):
            output = async_to_sync(activity_environment.run)(
                refresh_sandbox_credentials,
                RefreshSandboxCredentialsInput(context=task_context, sandbox_id="sandbox-abc"),
            )

        assert output.refreshed_kinds == ["github"]
        assert output.next_refresh_seconds == 20 * 60
        assert output.sandbox_gone is False

        # git remote rewrite + env-file read both ran against the sandbox.
        assert any("git remote set-url origin" in str(c.args[0]) for c in sandbox.execute.call_args_list)
        sandbox.write_file.assert_called_once()

        track_event.assert_called_once()
        event_name = track_event.call_args[0][0]
        assert event_name == "sandbox_credentials_refreshed"
        assert track_event.call_args.kwargs["properties"]["refreshed_kinds"] == ["github"]

    def test_credential_failure_is_non_fatal(self, activity_environment, task_context, test_task, sandbox):
        with (
            patch(
                "products.tasks.backend.temporal.process_task.activities.refresh_sandbox_credentials.Sandbox.get_by_id",
                return_value=sandbox,
            ),
            patch(
                "products.tasks.backend.temporal.process_task.sandbox_credentials.get_sandbox_github_token",
                side_effect=RuntimeError("token mint failed"),
            ),
            patch("products.tasks.backend.temporal.process_task.activities.refresh_sandbox_credentials.track_event"),
        ):
            # Must not raise — a failed refresh should not kill the run.
            output = async_to_sync(activity_environment.run)(
                refresh_sandbox_credentials,
                RefreshSandboxCredentialsInput(context=task_context, sandbox_id="sandbox-abc"),
            )

        assert output.refreshed_kinds == []
        # All credentials failed -> no per-token interval, so fall back to the default cadence.
        assert output.next_refresh_seconds == DEFAULT_REFRESH_INTERVAL_SECONDS
        assert output.sandbox_gone is False

    def test_skips_refresh_when_sandbox_not_running(self, activity_environment, task_context, test_task, sandbox):
        sandbox.is_running.return_value = False
        with (
            patch(
                "products.tasks.backend.temporal.process_task.activities.refresh_sandbox_credentials.Sandbox.get_by_id",
                return_value=sandbox,
            ),
            patch(
                "products.tasks.backend.temporal.process_task.sandbox_credentials.get_sandbox_github_token"
            ) as get_token,
            patch("products.tasks.backend.temporal.process_task.activities.refresh_sandbox_credentials.track_event"),
            patch(
                "products.tasks.backend.temporal.process_task.activities.refresh_sandbox_credentials.increment_credential_refresh"
            ) as increment,
        ):
            output = async_to_sync(activity_environment.run)(
                refresh_sandbox_credentials,
                RefreshSandboxCredentialsInput(context=task_context, sandbox_id="sandbox-abc"),
            )

        assert output.refreshed_kinds == []
        assert output.next_refresh_seconds == DEFAULT_REFRESH_INTERVAL_SECONDS
        assert output.sandbox_gone is True
        get_token.assert_not_called()
        sandbox.execute.assert_not_called()
        increment.assert_called_once_with("github", "skipped")

    def test_skips_refresh_when_sandbox_gone(self, activity_environment, task_context, test_task):
        # A reaped/unreachable sandbox surfaces as SandboxNotFoundError from get_by_id.
        # The refresh must skip gracefully rather than fail the activity (which would
        # fire a spurious "task failed" alert after the run's PR is already open).
        with (
            patch(
                "products.tasks.backend.temporal.process_task.activities.refresh_sandbox_credentials.Sandbox.get_by_id",
                side_effect=SandboxNotFoundError(
                    "Sandbox sandbox-abc not found",
                    {"sandbox_id": "sandbox-abc"},
                    cause=RuntimeError("Deadline Exceeded"),
                ),
            ),
            patch(
                "products.tasks.backend.temporal.process_task.sandbox_credentials.get_sandbox_github_token"
            ) as get_token,
            patch(
                "products.tasks.backend.temporal.process_task.activities.refresh_sandbox_credentials.track_event"
            ) as track_event,
            patch(
                "products.tasks.backend.temporal.process_task.activities.refresh_sandbox_credentials.increment_credential_refresh"
            ) as increment,
        ):
            # Must not raise — a gone sandbox should not fail the activity.
            output = async_to_sync(activity_environment.run)(
                refresh_sandbox_credentials,
                RefreshSandboxCredentialsInput(context=task_context, sandbox_id="sandbox-abc"),
            )

        assert output.refreshed_kinds == []
        assert output.next_refresh_seconds == DEFAULT_REFRESH_INTERVAL_SECONDS
        assert output.sandbox_gone is True
        get_token.assert_not_called()
        increment.assert_called_once_with("github", "skipped")
        track_event.assert_not_called()

    def test_sandbox_stopped_mid_refresh_counts_as_skipped(
        self, activity_environment, task_context, test_task, sandbox
    ):
        sandbox.execute.side_effect = SandboxNotRunningError(
            "Sandbox not in running state.", {"sandbox_id": "sandbox-abc"}, cause=RuntimeError("not running")
        )
        with (
            patch(
                "products.tasks.backend.temporal.process_task.activities.refresh_sandbox_credentials.Sandbox.get_by_id",
                return_value=sandbox,
            ),
            patch(
                "products.tasks.backend.temporal.process_task.sandbox_credentials.get_sandbox_github_token",
                return_value="ghs_fresh",
            ),
            patch("products.tasks.backend.temporal.process_task.activities.refresh_sandbox_credentials.track_event"),
            patch(
                "products.tasks.backend.temporal.process_task.activities.refresh_sandbox_credentials.increment_credential_refresh"
            ) as increment,
        ):
            output = async_to_sync(activity_environment.run)(
                refresh_sandbox_credentials,
                RefreshSandboxCredentialsInput(context=task_context, sandbox_id="sandbox-abc"),
            )

        assert output.refreshed_kinds == []
        assert output.sandbox_gone is True
        increment.assert_called_once_with("github", "skipped")

    def test_genuine_execution_error_counts_as_failed(self, activity_environment, task_context, test_task, sandbox):
        sandbox.execute.side_effect = SandboxExecutionError(
            "Failed to execute command", {"sandbox_id": "sandbox-abc"}, cause=RuntimeError("network blip")
        )
        with (
            patch(
                "products.tasks.backend.temporal.process_task.activities.refresh_sandbox_credentials.Sandbox.get_by_id",
                return_value=sandbox,
            ),
            patch(
                "products.tasks.backend.temporal.process_task.sandbox_credentials.get_sandbox_github_token",
                return_value="ghs_fresh",
            ),
            patch("products.tasks.backend.temporal.process_task.activities.refresh_sandbox_credentials.track_event"),
            patch(
                "products.tasks.backend.temporal.process_task.activities.refresh_sandbox_credentials.increment_credential_refresh"
            ) as increment,
        ):
            output = async_to_sync(activity_environment.run)(
                refresh_sandbox_credentials,
                RefreshSandboxCredentialsInput(context=task_context, sandbox_id="sandbox-abc"),
            )

        assert output.refreshed_kinds == []
        increment.assert_called_once_with("github", "failed")
