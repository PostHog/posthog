import uuid
import dataclasses

import pytest
from unittest.mock import MagicMock, patch

from django.db import OperationalError

from asgiref.sync import async_to_sync

from posthog.models.integration import Integration

from products.tasks.backend.exceptions import SandboxExecutionError, SandboxNotFoundError, SandboxNotRunningError
from products.tasks.backend.logic.services.sandbox import ExecutionResult
from products.tasks.backend.models import TASK_OWNERSHIP_VERSION_STATE_KEY, Task, TaskRun
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
            patch("products.tasks.backend.logic.services.agent_command.send_agent_command") as send_agent_command,
        ):
            output = async_to_sync(activity_environment.run)(
                refresh_sandbox_credentials,
                RefreshSandboxCredentialsInput(context=task_context, sandbox_id="sandbox-abc"),
            )

        assert output.refreshed_kinds == ["github"]
        assert output.next_refresh_seconds == 20 * 60
        assert output.sandbox_gone is False
        send_agent_command.assert_not_called()

        # git remote rewrite + env-file read both ran against the sandbox.
        assert any("git remote set-url origin" in str(c.args[0]) for c in sandbox.execute.call_args_list)
        sandbox.write_file.assert_called_once()

        track_event.assert_called_once()
        event_name = track_event.call_args[0][0]
        assert event_name == "sandbox_credentials_refreshed"
        assert track_event.call_args.kwargs["properties"]["refreshed_kinds"] == ["github"]

    def test_stops_refreshing_after_task_handoff(self, activity_environment, task_context, test_task, sandbox):
        test_task.state = {TASK_OWNERSHIP_VERSION_STATE_KEY: "new-owner"}
        test_task.save(update_fields=["state", "updated_at"])

        with patch(
            "products.tasks.backend.temporal.process_task.activities.refresh_sandbox_credentials.Sandbox.get_by_id",
            return_value=sandbox,
        ) as get_sandbox:
            output = async_to_sync(activity_environment.run)(
                refresh_sandbox_credentials,
                RefreshSandboxCredentialsInput(context=task_context, sandbox_id="sandbox-abc"),
            )

        assert output.refreshed_kinds == []
        assert output.no_credentials_left is True
        get_sandbox.assert_not_called()

    def test_promoted_run_refreshes_as_user_not_the_team_installation(
        self, activity_environment, task_context, test_task, test_task_run, sandbox
    ):
        # The context is captured at workflow start, so a run promoted to user authorship since
        # then still reads as bot-authored here — and would get the team installation token
        # re-applied over the user's, widening access to every repo that installation covers.
        TaskRun.objects.filter(id=test_task_run.id).update(state={"pr_authorship_mode": "user"})

        with (
            patch(
                "products.tasks.backend.temporal.process_task.activities.refresh_sandbox_credentials.Sandbox.get_by_id",
                return_value=sandbox,
            ),
            patch(
                "products.tasks.backend.temporal.process_task.sandbox_credentials.get_sandbox_github_token",
                return_value="ghu_user",
            ) as get_token,
            patch("products.tasks.backend.temporal.process_task.activities.refresh_sandbox_credentials.track_event"),
        ):
            async_to_sync(activity_environment.run)(
                refresh_sandbox_credentials,
                RefreshSandboxCredentialsInput(context=task_context, sandbox_id="sandbox-abc"),
            )

        assert get_token.call_args.kwargs["state"]["pr_authorship_mode"] == "user"

    def test_retries_transient_db_connection_drop(self, activity_environment, task_context, test_task, sandbox):
        # A pooled pgbouncer connection dropped mid-request raises OperationalError on the
        # activity's early Task read. The retry-once guard must evict the dead connection and
        # succeed on the second attempt rather than letting it escape as error-tracking noise.
        with (
            patch(
                "products.tasks.backend.temporal.process_task.activities.refresh_sandbox_credentials.Task"
            ) as mock_task,
            patch(
                "products.tasks.backend.temporal.process_task.activities.refresh_sandbox_credentials.Sandbox.get_by_id",
                return_value=sandbox,
            ),
            patch(
                "products.tasks.backend.temporal.process_task.sandbox_credentials.get_sandbox_github_token",
                return_value="ghs_fresh",
            ),
            patch("products.tasks.backend.temporal.process_task.activities.refresh_sandbox_credentials.track_event"),
        ):
            mock_task.DoesNotExist = Task.DoesNotExist
            mock_task.objects.select_related.return_value.get.side_effect = [
                OperationalError("server closed the connection unexpectedly"),
                test_task,
            ]

            output = async_to_sync(activity_environment.run)(
                refresh_sandbox_credentials,
                RefreshSandboxCredentialsInput(context=task_context, sandbox_id="sandbox-abc"),
            )

        assert mock_task.objects.select_related.return_value.get.call_count == 2
        assert output.refreshed_kinds == ["github"]

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

    def test_missing_task_returns_task_gone_flag(self, activity_environment, task_context, test_task, sandbox):
        # Rows hard-deleted mid-run (team deletion cascade) must surface as an output
        # flag the refresh loop stops on, not as an error the loop swallows and retries.
        context = dataclasses.replace(task_context, task_id=str(uuid.uuid4()))
        with patch(
            "products.tasks.backend.temporal.process_task.activities.refresh_sandbox_credentials.Sandbox.get_by_id",
            return_value=sandbox,
        ):
            output = async_to_sync(activity_environment.run)(
                refresh_sandbox_credentials,
                RefreshSandboxCredentialsInput(context=context, sandbox_id="sandbox-abc"),
            )

        assert output.task_gone is True
        assert output.refreshed_kinds == []
        sandbox.execute.assert_not_called()

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

    def test_deleted_integration_counts_as_orphaned_and_stops_loop(
        self, activity_environment, task_context, test_task, sandbox
    ):
        # Delete via a queryset so the fixture instances keep their pks and teardown
        # (integration.delete(), task.soft_delete()) still works on them.
        Integration.objects.filter(id=test_task.github_integration_id).delete()
        test_task.refresh_from_db()
        with (
            patch(
                "products.tasks.backend.temporal.process_task.activities.refresh_sandbox_credentials.Sandbox.get_by_id",
                return_value=sandbox,
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

        assert output.orphaned_kinds == ["github"]
        assert output.no_credentials_left is True
        assert output.refreshed_kinds == []
        assert output.sandbox_gone is False
        increment.assert_called_once_with("github", "orphaned")

    def test_excluded_kinds_report_nothing_left(self, activity_environment, task_context, test_task, sandbox):
        with (
            patch(
                "products.tasks.backend.temporal.process_task.activities.refresh_sandbox_credentials.Sandbox.get_by_id",
                return_value=sandbox,
            ),
            patch(
                "products.tasks.backend.temporal.process_task.activities.refresh_sandbox_credentials.track_event"
            ) as track_event,
        ):
            output = async_to_sync(activity_environment.run)(
                refresh_sandbox_credentials,
                RefreshSandboxCredentialsInput(
                    context=task_context, sandbox_id="sandbox-abc", exclude_kinds=["github"]
                ),
            )

        assert output.no_credentials_left is True
        assert output.sandbox_gone is False
        assert output.refreshed_kinds == []
        sandbox.execute.assert_not_called()
        track_event.assert_not_called()

    def test_sandbox_gone_wins_over_excluded_kinds(self, activity_environment, task_context, test_task):
        with (
            patch(
                "products.tasks.backend.temporal.process_task.activities.refresh_sandbox_credentials.Sandbox.get_by_id",
                side_effect=SandboxNotFoundError(
                    "Sandbox sandbox-abc not found",
                    {"sandbox_id": "sandbox-abc"},
                    cause=RuntimeError("Deadline Exceeded"),
                ),
            ),
            patch("products.tasks.backend.temporal.process_task.activities.refresh_sandbox_credentials.track_event"),
        ):
            output = async_to_sync(activity_environment.run)(
                refresh_sandbox_credentials,
                RefreshSandboxCredentialsInput(
                    context=task_context, sandbox_id="sandbox-abc", exclude_kinds=["github"]
                ),
            )

        assert output.sandbox_gone is True
        assert output.no_credentials_left is False

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
