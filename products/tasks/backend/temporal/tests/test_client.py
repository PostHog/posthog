import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from products.tasks.backend.temporal.client import (
    execute_cloud_workflow,
    is_workflow_running,
    send_process_task_heartbeat,
)
from temporalio.service import RPCError


pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]


class TestExecuteCloudWorkflow:
    def test_execute_cloud_workflow_success(self):
        mock_client = MagicMock()
        mock_client.start_workflow = AsyncMock()

        with patch(
            "products.tasks.backend.temporal.client.sync_connect",
            return_value=mock_client,
        ):
            workflow_id = execute_cloud_workflow(
                task_id="test-task",
                run_id="test-run",
                team_id=1,
            )

        assert workflow_id is not None
        assert workflow_id.startswith("task-processing-test-run-")

    def test_execute_cloud_workflow_with_initial_prompt(self):
        mock_client = MagicMock()
        mock_client.start_workflow = AsyncMock()

        with patch(
            "products.tasks.backend.temporal.client.sync_connect",
            return_value=mock_client,
        ):
            workflow_id = execute_cloud_workflow(
                task_id="test-task",
                run_id="test-run",
                team_id=1,
                initial_prompt="Hello, agent!",
            )

        assert workflow_id is not None
        call_args = mock_client.start_workflow.call_args
        workflow_input = call_args[0][1]
        assert workflow_input.initial_prompt == "Hello, agent!"
        assert workflow_input.execution_mode == "cloud"

    def test_execute_cloud_workflow_failure_returns_none(self):
        with patch(
            "products.tasks.backend.temporal.client.sync_connect",
            side_effect=Exception("Connection failed"),
        ):
            workflow_id = execute_cloud_workflow(
                task_id="test-task",
                run_id="test-run",
                team_id=1,
            )

        assert workflow_id is None


class TestSendProcessTaskHeartbeat:
    def test_send_heartbeat_success(self):
        mock_client = MagicMock()
        mock_handle = MagicMock()
        mock_handle.signal = AsyncMock()
        mock_client.get_workflow_handle = MagicMock(return_value=mock_handle)

        async def mock_run_until_complete(coro):
            return await coro

        with patch(
            "products.tasks.backend.temporal.client.sync_connect",
            return_value=mock_client,
        ), patch(
            "asyncio.get_event_loop"
        ) as mock_loop:
            mock_loop.return_value.run_until_complete = lambda coro: None
            result = send_process_task_heartbeat("test-run", "test-workflow-id")

        assert result is True
        mock_client.get_workflow_handle.assert_called_once_with("test-workflow-id")

    def test_send_heartbeat_failure_returns_false(self):
        mock_client = MagicMock()
        mock_client.get_workflow_handle = MagicMock(side_effect=Exception("Not found"))

        with patch(
            "products.tasks.backend.temporal.client.sync_connect",
            return_value=mock_client,
        ):
            result = send_process_task_heartbeat("test-run", "test-workflow-id")

        assert result is False

    def test_send_heartbeat_rpc_error_returns_false(self):
        mock_client = MagicMock()
        mock_client.get_workflow_handle = MagicMock(
            side_effect=RPCError("Workflow not found", status=None, raw_grpc_status=None)
        )

        with patch(
            "products.tasks.backend.temporal.client.sync_connect",
            return_value=mock_client,
        ):
            result = send_process_task_heartbeat("test-run", "test-workflow-id")

        assert result is False


class TestIsWorkflowRunning:
    def test_workflow_running(self):
        mock_client = MagicMock()
        mock_handle = MagicMock()
        mock_desc = MagicMock()
        mock_desc.status.name = "RUNNING"
        mock_handle.describe = AsyncMock(return_value=mock_desc)
        mock_client.get_workflow_handle = MagicMock(return_value=mock_handle)

        with patch(
            "products.tasks.backend.temporal.client.sync_connect",
            return_value=mock_client,
        ):
            result = is_workflow_running("test-workflow-id")

        assert result is True

    def test_workflow_not_running(self):
        mock_client = MagicMock()
        mock_handle = MagicMock()
        mock_desc = MagicMock()
        mock_desc.status.name = "COMPLETED"
        mock_handle.describe = AsyncMock(return_value=mock_desc)
        mock_client.get_workflow_handle = MagicMock(return_value=mock_handle)

        with patch(
            "products.tasks.backend.temporal.client.sync_connect",
            return_value=mock_client,
        ):
            result = is_workflow_running("test-workflow-id")

        assert result is False

    def test_workflow_not_found_returns_false(self):
        mock_client = MagicMock()
        mock_client.get_workflow_handle = MagicMock(
            side_effect=RPCError("Not found", status=None, raw_grpc_status=None)
        )

        with patch(
            "products.tasks.backend.temporal.client.sync_connect",
            return_value=mock_client,
        ):
            result = is_workflow_running("nonexistent-workflow")

        assert result is False
