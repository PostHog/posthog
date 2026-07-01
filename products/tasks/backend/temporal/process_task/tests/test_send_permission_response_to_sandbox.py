from types import SimpleNamespace

import pytest
from unittest.mock import MagicMock, patch

from products.tasks.backend.logic.services.agent_command import CommandResult
from products.tasks.backend.temporal.process_task.activities.send_permission_response_to_sandbox import (
    SendPermissionDenialGuidanceInput,
    SendPermissionResponseToSandboxInput,
    send_permission_denial_guidance,
    send_permission_response_to_sandbox,
)


@pytest.fixture
def patches():
    with (
        patch(
            "products.tasks.backend.temporal.process_task.activities.send_permission_response_to_sandbox.TaskRun"
        ) as mock_task_run_cls,
        patch(
            "products.tasks.backend.temporal.process_task.activities.send_permission_response_to_sandbox.User"
        ) as mock_user_cls,
        patch(
            "products.tasks.backend.temporal.process_task.activities.send_permission_response_to_sandbox.create_sandbox_connection_token"
        ) as mock_create_token,
        patch(
            "products.tasks.backend.temporal.process_task.activities.send_permission_response_to_sandbox.send_user_message"
        ) as mock_send_user_message,
        patch(
            "products.tasks.backend.temporal.process_task.activities.send_permission_response_to_sandbox.send_agent_command"
        ) as mock_send_agent_command,
    ):
        task_run = MagicMock()
        task_run.id = "run-1"
        actor = SimpleNamespace(id=42, distinct_id="actor-distinct-id")
        mock_task_run_cls.objects.select_related.return_value.get.return_value = task_run
        mock_user_cls.objects.get.return_value = actor
        mock_create_token.return_value = "sandbox-token"
        mock_send_user_message.return_value = CommandResult(success=True, status_code=200)
        mock_send_agent_command.return_value = CommandResult(success=True, status_code=200)

        yield {
            "task_run_cls": mock_task_run_cls,
            "task_run": task_run,
            "user_cls": mock_user_cls,
            "actor": actor,
            "create_token": mock_create_token,
            "send_user_message": mock_send_user_message,
            "send_agent_command": mock_send_agent_command,
        }


class TestSendPermissionResponseToSandbox:
    def test_approve_sends_permission_response_with_actor_token(self, patches):
        send_permission_response_to_sandbox(
            SendPermissionResponseToSandboxInput(
                run_id="run-1",
                request_id="perm-1",
                option_id="allow",
                actor_user_id=42,
                actor_slack_user_id="U123",
                broker_reason="slack_human_response",
            )
        )

        patches["create_token"].assert_called_once_with(
            patches["task_run"],
            user_id=42,
            distinct_id="actor-distinct-id",
        )
        patches["send_user_message"].assert_not_called()
        patches["send_agent_command"].assert_called_once_with(
            patches["task_run"],
            method="permission_response",
            params={"requestId": "perm-1", "optionId": "allow"},
            auth_token="sandbox-token",
            timeout=30,
        )
        patches["task_run_cls"].update_state_atomic.assert_called_once_with(
            "run-1",
            updates={
                "slack_actor_user_id": 42,
                "slack_permission_response_last_request_id": "perm-1",
                "slack_permission_response_last_option_id": "allow",
                "slack_actor_slack_user_id": "U123",
                "slack_permission_broker_last_reason": "slack_human_response",
            },
        )

    def test_denial_records_rejection_state(self, patches):
        send_permission_response_to_sandbox(
            SendPermissionResponseToSandboxInput(
                run_id="run-1",
                request_id="perm-1",
                option_id="reject",
                actor_user_id=42,
                actor_slack_user_id="U123",
                is_denial=True,
            )
        )

        patches["task_run_cls"].update_state_atomic.assert_called_once_with(
            "run-1",
            updates={
                "slack_actor_user_id": 42,
                "slack_permission_response_last_request_id": "perm-1",
                "slack_permission_response_last_option_id": "reject",
                "slack_actor_slack_user_id": "U123",
                "slack_permission_rejected": True,
                "slack_permission_rejected_request_id": "perm-1",
            },
        )

    def test_delivery_failure_raises_without_state_update(self, patches):
        patches["send_agent_command"].return_value = CommandResult(
            success=False,
            status_code=502,
            error="sandbox unavailable",
        )

        with pytest.raises(RuntimeError, match="sandbox unavailable"):
            send_permission_response_to_sandbox(
                SendPermissionResponseToSandboxInput(
                    run_id="run-1",
                    request_id="perm-1",
                    option_id="allow",
                    actor_user_id=42,
                )
            )

        patches["task_run_cls"].update_state_atomic.assert_not_called()


class TestSendPermissionDenialGuidance:
    def test_sends_guidance_with_actor_token(self, patches):
        send_permission_denial_guidance(
            SendPermissionDenialGuidanceInput(
                run_id="run-1",
                request_id="perm-1",
                actor_user_id=42,
                denial_message="The user denied your approval request.",
            )
        )

        patches["send_user_message"].assert_called_once_with(
            patches["task_run"],
            "The user denied your approval request.",
            auth_token="sandbox-token",
            timeout=10,
        )
        patches["send_agent_command"].assert_not_called()

    def test_guidance_delivery_failure_raises(self, patches):
        patches["send_user_message"].return_value = CommandResult(
            success=False,
            status_code=502,
            error="sandbox unavailable",
        )

        with pytest.raises(RuntimeError, match="sandbox unavailable"):
            send_permission_denial_guidance(
                SendPermissionDenialGuidanceInput(
                    run_id="run-1",
                    request_id="perm-1",
                    actor_user_id=42,
                    denial_message="The user denied your approval request.",
                )
            )
