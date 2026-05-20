import pytest
from unittest.mock import AsyncMock, patch

from django.conf import settings

from temporalio.common import WorkflowIDReusePolicy

from products.tasks.backend.temporal.execute_sandbox.workflow import PARENT_ATTACHED_SIGNAL, ExecuteSandboxInput
from products.tasks.backend.temporal.task_management.activities.ensure_execute_sandbox_started import (
    EnsureExecuteSandboxStartedInput,
    ensure_execute_sandbox_started,
)


@pytest.mark.asyncio
class TestEnsureExecuteSandboxStarted:
    async def test_invokes_signal_with_start_using_allow_duplicate(self, activity_environment):
        # The activity uses Signal-With-Start as a single atomic op: if the
        # sandbox workflow is already running under `workflow_id`, the
        # bootstrap signal lands on it; otherwise a fresh execution is
        # started with the same signal pre-queued. ALLOW_DUPLICATE lets us
        # re-use the deterministic workflow id once the prior execution closed.
        client = AsyncMock()
        client.start_workflow = AsyncMock()

        input_data = EnsureExecuteSandboxStartedInput(
            workflow_id="sandbox-wf-id",
            workflow_input=ExecuteSandboxInput(
                run_id="run-1",
                parent_workflow_id="parent-wf-id",
                create_pr=False,
                slack_thread_context={"channel": "C1"},
                posthog_mcp_scopes="full",
            ),
            bootstrap_ack_id="ack-bootstrap",
        )

        with patch(
            "products.tasks.backend.temporal.task_management.activities.ensure_execute_sandbox_started.async_connect",
            AsyncMock(return_value=client),
        ):
            await activity_environment.run(ensure_execute_sandbox_started, input_data)

        client.start_workflow.assert_awaited_once()
        args, kwargs = client.start_workflow.call_args
        assert args[0] == "execute-sandbox"
        assert args[1] is input_data.workflow_input
        assert kwargs["id"] == "sandbox-wf-id"
        assert kwargs["task_queue"] == settings.TASKS_TASK_QUEUE
        assert kwargs["id_reuse_policy"] == WorkflowIDReusePolicy.ALLOW_DUPLICATE
        assert kwargs["start_signal"] == PARENT_ATTACHED_SIGNAL
        # The bootstrap signal is what the orchestrator ACKs on to confirm the
        # child is alive — args are (ack_id, parent_workflow_id) in that order.
        assert kwargs["start_signal_args"] == ["ack-bootstrap", "parent-wf-id"]
