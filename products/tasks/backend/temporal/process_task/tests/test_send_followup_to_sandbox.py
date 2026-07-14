import pytest
from unittest.mock import MagicMock, patch

from temporalio.exceptions import ApplicationError

from products.tasks.backend.logic.services.agent_command import CommandResult
from products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox import (
    SEND_FOLLOWUP_MAX_ATTEMPTS,
    SendFollowupToSandboxInput,
    send_followup_to_sandbox,
)
from products.tasks.backend.temporal.process_task.tests.helpers import make_task_run_mock

pytestmark = pytest.mark.django_db


class TestSendFollowupActivityRefreshOrdering:
    """Refresh call must precede user_message, and the activity must succeed
    when refresh fails (non-fatal) as long as user_message succeeds."""

    @pytest.fixture
    def _patches(self):
        """Patch everything the activity touches at module boundary."""
        with (
            patch(
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.TaskRun"
            ) as mock_task_run_cls,
            patch(
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.create_sandbox_connection_token"
            ) as mock_conn_token,
            patch(
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.ensure_sandbox_identity"
            ) as mock_refresh,
            patch(
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.send_user_message"
            ) as mock_user_msg,
            patch(
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox._write_turn_complete"
            ),
            patch(
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox._write_error_and_complete"
            ),
        ):
            task_run = make_task_run_mock()
            task_run.task.created_by = MagicMock(id=42, distinct_id="u42")
            mock_task_run_cls.objects.select_related.return_value.get.return_value = task_run
            mock_conn_token.return_value = "jwt"

            yield {
                "task_run": task_run,
                "refresh": mock_refresh,
                "user_msg": mock_user_msg,
                "conn_token": mock_conn_token,
            }

    def test_refresh_called_before_user_message(self, _patches):
        call_order: list[str] = []

        def _record_refresh(*a, **kw):
            call_order.append("refresh")

        def _record_user_msg(*a, **kw):
            call_order.append("user_message")
            return CommandResult(success=True, status_code=200, data={"result": {"stopReason": "end_turn"}})

        _patches["refresh"].side_effect = _record_refresh
        _patches["user_msg"].side_effect = _record_user_msg

        send_followup_to_sandbox(SendFollowupToSandboxInput(run_id="run-1", message="hi", posthog_mcp_scopes="full"))

        assert call_order == ["refresh", "user_message"]

    def test_scopes_flow_from_input_to_refresh(self, _patches):
        _patches["user_msg"].return_value = CommandResult(success=True, status_code=200)

        send_followup_to_sandbox(SendFollowupToSandboxInput(run_id="run-1", message="hi", posthog_mcp_scopes="full"))

        _patches["refresh"].assert_called_once()
        args, kwargs = _patches["refresh"].call_args
        assert args[0] is _patches["task_run"]
        assert kwargs["posthog_mcp_scopes"] == "full"
        assert kwargs["auth_token"] == "jwt"

    def test_default_scope_is_read_only(self, _patches):
        _patches["user_msg"].return_value = CommandResult(success=True, status_code=200)

        send_followup_to_sandbox(SendFollowupToSandboxInput(run_id="run-1", message="hi"))

        _args, kwargs = _patches["refresh"].call_args
        assert kwargs["posthog_mcp_scopes"] == "read_only"


class TestSendFollowupTurnTimeout:
    """A read timeout (turn_in_flight) means the message was delivered and the
    turn is still running — the activity must not fail the run or write stream
    markers. A 504 *response* leaves delivery unknown and must retry; any other
    delivery failure stays fatal."""

    @pytest.fixture
    def _patches(self):
        with (
            patch(
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.TaskRun"
            ) as mock_task_run_cls,
            patch(
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.create_sandbox_connection_token"
            ) as mock_conn_token,
            patch(
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.ensure_sandbox_identity"
            ),
            patch(
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox.send_user_message"
            ) as mock_user_msg,
            patch(
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox._write_turn_complete"
            ) as mock_turn_complete,
            patch(
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox._write_error_and_complete"
            ) as mock_error,
        ):
            task_run = make_task_run_mock()
            task_run.task.created_by = MagicMock(id=42, distinct_id="u42")
            mock_task_run_cls.objects.select_related.return_value.get.return_value = task_run
            mock_conn_token.return_value = "jwt"

            yield {
                "user_msg": mock_user_msg,
                "turn_complete": mock_turn_complete,
                "error": mock_error,
            }

    def test_read_timeout_is_non_fatal_and_writes_no_markers(self, _patches):
        # Regression: a turn longer than FOLLOWUP_TIMEOUT_SECONDS used to fail
        # the run and destroy a healthy sandbox mid-work.
        _patches["user_msg"].return_value = CommandResult(
            success=False, status_code=504, error="Sandbox request timed out", retryable=True, turn_in_flight=True
        )

        send_followup_to_sandbox(SendFollowupToSandboxInput(run_id="run-1", message="hi"))

        _patches["error"].assert_not_called()
        _patches["turn_complete"].assert_not_called()

    def test_undelivered_message_stays_fatal(self, _patches):
        # The non-fatal carve-out must stay scoped to delivered-but-running —
        # a connection failure means the user's message never arrived.
        _patches["user_msg"].return_value = CommandResult(
            success=False, status_code=502, error="Connection to sandbox failed", retryable=True
        )

        with pytest.raises(ApplicationError, match="Connection to sandbox failed") as exc_info:
            send_followup_to_sandbox(SendFollowupToSandboxInput(run_id="run-1", message="hi"))

        assert exc_info.value.non_retryable is True
        _patches["error"].assert_called_once()
        _patches["turn_complete"].assert_not_called()

    def test_response_504_retries_without_sentinel(self, _patches):
        # Regression: a genuine 504 *response* (tunnel gateway timeout,
        # delivery unknown) used to be conflated with the read-timeout case
        # and silently treated as delivered — losing the user's message.
        _patches["user_msg"].return_value = CommandResult(
            success=False, status_code=504, error="Sandbox returned 504", retryable=True
        )

        with pytest.raises(ApplicationError, match="delivery unknown") as exc_info:
            send_followup_to_sandbox(SendFollowupToSandboxInput(run_id="run-1", message="hi"))

        assert exc_info.value.non_retryable is False
        _patches["error"].assert_not_called()
        _patches["turn_complete"].assert_not_called()

    def test_response_504_final_attempt_writes_sentinel_and_fails(self, _patches):
        _patches["user_msg"].return_value = CommandResult(
            success=False, status_code=504, error="Sandbox returned 504", retryable=True
        )

        with (
            patch(
                "products.tasks.backend.temporal.process_task.activities.send_followup_to_sandbox._current_attempt",
                return_value=SEND_FOLLOWUP_MAX_ATTEMPTS,
            ),
            pytest.raises(ApplicationError, match="send_followup failed") as exc_info,
        ):
            send_followup_to_sandbox(SendFollowupToSandboxInput(run_id="run-1", message="hi"))

        assert exc_info.value.non_retryable is True
        _patches["error"].assert_called_once()
        _patches["turn_complete"].assert_not_called()

    def test_duplicate_delivery_skips_markers(self, _patches):
        # A retried attempt whose message the agent-server already accepted
        # must not write a synthetic turn_complete — the turn is still running
        # and the event stream owns its completion.
        _patches["user_msg"].return_value = CommandResult(
            success=True,
            status_code=200,
            data={"result": {"duplicate": True, "stopReason": "duplicate_delivery"}},
        )

        send_followup_to_sandbox(SendFollowupToSandboxInput(run_id="run-1", message="hi", message_id="m-1"))

        _patches["error"].assert_not_called()
        _patches["turn_complete"].assert_not_called()

    def test_message_id_forwarded_to_sandbox(self, _patches):
        _patches["user_msg"].return_value = CommandResult(success=True, status_code=200)

        send_followup_to_sandbox(SendFollowupToSandboxInput(run_id="run-1", message="hi", message_id="m-1"))

        _, kwargs = _patches["user_msg"].call_args
        assert kwargs["message_id"] == "m-1"
