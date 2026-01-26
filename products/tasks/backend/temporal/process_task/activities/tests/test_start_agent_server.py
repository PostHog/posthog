import pytest
from unittest.mock import MagicMock, patch

from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext
from products.tasks.backend.temporal.process_task.activities.start_agent_server import (
    StartAgentServerInput,
    start_agent_server,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.django_db(transaction=True)]


def _make_context(
    task_id: str = "test-task-id",
    run_id: str = "test-run-id",
    team_id: int = 1,
    repository: str = "posthog/posthog-js",
) -> TaskProcessingContext:
    return TaskProcessingContext(
        task_id=task_id,
        run_id=run_id,
        team_id=team_id,
        github_integration_id=1,
        repository=repository,
        distinct_id="test-user",
        create_pr=True,
    )


class TestStartAgentServerActivity:
    async def test_start_agent_server_success(self):
        context = _make_context()
        sandbox_mock = MagicMock()
        sandbox_mock.execute_background = MagicMock()
        sandbox_mock.execute = MagicMock(return_value=MagicMock(exit_code=0, stdout="12345\n", stderr=""))

        with patch(
            "products.tasks.backend.temporal.process_task.activities.start_agent_server.Sandbox.get_by_id",
            return_value=sandbox_mock,
        ):
            result = await start_agent_server(StartAgentServerInput(context=context, sandbox_id="test-sandbox"))

        assert result.success is True
        assert result.error is None
        sandbox_mock.execute_background.assert_called_once()
        call_args = sandbox_mock.execute_background.call_args[0][0]
        assert "--taskId test-task-id" in call_args
        assert "--runId test-run-id" in call_args
        assert "--repositoryPath /tmp/workspace/repos/posthog/posthog-js" in call_args

    async def test_start_agent_server_with_initial_prompt(self):
        context = _make_context()
        sandbox_mock = MagicMock()
        sandbox_mock.execute_background = MagicMock()
        sandbox_mock.execute = MagicMock(return_value=MagicMock(exit_code=0, stdout="12345\n", stderr=""))

        with patch(
            "products.tasks.backend.temporal.process_task.activities.start_agent_server.Sandbox.get_by_id",
            return_value=sandbox_mock,
        ):
            result = await start_agent_server(
                StartAgentServerInput(
                    context=context,
                    sandbox_id="test-sandbox",
                    initial_prompt="Hello, agent!",
                )
            )

        assert result.success is True
        call_args = sandbox_mock.execute_background.call_args[0][0]
        assert "--initialPrompt" in call_args

    async def test_start_agent_server_process_not_found(self):
        context = _make_context()
        sandbox_mock = MagicMock()
        sandbox_mock.execute_background = MagicMock()
        sandbox_mock.execute = MagicMock(
            side_effect=[
                MagicMock(exit_code=1, stdout="", stderr=""),
                MagicMock(exit_code=0, stdout="Error log content", stderr=""),
            ]
        )

        with patch(
            "products.tasks.backend.temporal.process_task.activities.start_agent_server.Sandbox.get_by_id",
            return_value=sandbox_mock,
        ):
            result = await start_agent_server(StartAgentServerInput(context=context, sandbox_id="test-sandbox"))

        assert result.success is False
        assert result.error is not None
        assert "process not found" in result.error.lower()

    async def test_start_agent_server_sandbox_not_found(self):
        context = _make_context()

        with patch(
            "products.tasks.backend.temporal.process_task.activities.start_agent_server.Sandbox.get_by_id",
            side_effect=Exception("Sandbox not found"),
        ):
            result = await start_agent_server(StartAgentServerInput(context=context, sandbox_id="nonexistent"))

        assert result.success is False
        assert result.error is not None
        assert "Sandbox not found" in result.error

    async def test_start_agent_server_handles_uppercase_repository(self):
        context = _make_context(repository="PostHog/PostHog-JS")
        sandbox_mock = MagicMock()
        sandbox_mock.execute_background = MagicMock()
        sandbox_mock.execute = MagicMock(return_value=MagicMock(exit_code=0, stdout="12345\n", stderr=""))

        with patch(
            "products.tasks.backend.temporal.process_task.activities.start_agent_server.Sandbox.get_by_id",
            return_value=sandbox_mock,
        ):
            result = await start_agent_server(StartAgentServerInput(context=context, sandbox_id="test-sandbox"))

        assert result.success is True
        call_args = sandbox_mock.execute_background.call_args[0][0]
        assert "/tmp/workspace/repos/posthog/posthog-js" in call_args
