import os

import pytest

from asgiref.sync import async_to_sync

from products.tasks.backend.services.sandbox import Sandbox, SandboxConfig, SandboxTemplate
from products.tasks.backend.temporal.exceptions import SandboxNotFoundError
from products.tasks.backend.temporal.process_task.activities.execute_task_in_sandbox import (
    ExecuteTaskInput,
    execute_task_in_sandbox,
)
from products.tasks.backend.temporal.process_task.activities.get_task_processing_context import TaskProcessingContext


@pytest.mark.skipif(
    not os.environ.get("MODAL_TOKEN_ID") or not os.environ.get("MODAL_TOKEN_SECRET"),
    reason="MODAL_TOKEN_ID and MODAL_TOKEN_SECRET environment variables not set",
)
class TestExecuteTaskInSandboxActivity:
    def _create_context(
        self, github_integration, repository, task_id="test-task-123", run_id="test-run-456", create_pr=True
    ):
        return TaskProcessingContext(
            task_id=task_id,
            run_id=run_id,
            team_id=github_integration.team_id,
            github_integration_id=github_integration.id,
            repository=repository,
            distinct_id="test-user-id",
            create_pr=create_pr,
        )

    @pytest.mark.django_db
    def test_execute_task_returns_success(self, activity_environment, github_integration):
        """execute_task is now a no-op that returns success (task execution happens via agent-server)."""
        config = SandboxConfig(
            name="test-execute-task",
            template=SandboxTemplate.DEFAULT_BASE,
        )

        sandbox = None
        try:
            sandbox = Sandbox.create(config)
            context = self._create_context(github_integration, "PostHog/posthog-js")

            input_data = ExecuteTaskInput(context=context, sandbox_id=sandbox.id)
            result = async_to_sync(activity_environment.run)(execute_task_in_sandbox, input_data)

            assert result.exit_code == 0

        finally:
            if sandbox:
                sandbox.destroy()

    @pytest.mark.django_db
    def test_execute_task_sandbox_not_found(self, activity_environment, github_integration):
        context = self._create_context(github_integration, "PostHog/posthog-js")
        input_data = ExecuteTaskInput(context=context, sandbox_id="non-existent-sandbox-id")

        with pytest.raises(SandboxNotFoundError):
            async_to_sync(activity_environment.run)(execute_task_in_sandbox, input_data)
