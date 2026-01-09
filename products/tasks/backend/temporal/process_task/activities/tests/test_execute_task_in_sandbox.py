import os

import pytest
from unittest.mock import patch

from asgiref.sync import async_to_sync

from products.tasks.backend.services.sandbox import Sandbox, SandboxConfig, SandboxTemplate
from products.tasks.backend.temporal.exceptions import SandboxNotFoundError, TaskExecutionFailedError
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
    def test_execute_task_success(self, activity_environment, github_integration):
        config = SandboxConfig(
            name="test-execute-task",
            template=SandboxTemplate.DEFAULT_BASE,
        )

        sandbox = None
        try:
            sandbox = Sandbox.create(config)
            context = self._create_context(github_integration, "PostHog/posthog-js")

            sandbox.clone_repository("PostHog/posthog-js", github_token="")

            with patch(
                "products.tasks.backend.temporal.process_task.activities.execute_task_in_sandbox.Sandbox._get_task_command"
            ) as mock_task_cmd:
                mock_task_cmd.return_value = "echo 'Task executed successfully'"

                input_data = ExecuteTaskInput(context=context, sandbox_id=sandbox.id)

                async_to_sync(activity_environment.run)(execute_task_in_sandbox, input_data)

                mock_task_cmd.assert_called_once_with(
                    "test-task-123", "test-run-456", "/tmp/workspace/repos/posthog/posthog-js", True
                )

        finally:
            if sandbox:
                sandbox.destroy()

    @pytest.mark.django_db
    def test_execute_task_failure(self, activity_environment, github_integration):
        config = SandboxConfig(
            name="test-execute-task-fail",
            template=SandboxTemplate.DEFAULT_BASE,
        )

        sandbox = None
        try:
            sandbox = Sandbox.create(config)
            context = self._create_context(
                github_integration, "PostHog/posthog-js", task_id="test-task-fail", run_id="test-run-fail"
            )

            sandbox.clone_repository("PostHog/posthog-js", github_token="")

            with patch(
                "products.tasks.backend.temporal.process_task.activities.execute_task_in_sandbox.Sandbox._get_task_command"
            ) as mock_task_cmd:
                mock_task_cmd.return_value = "exit 1"

                input_data = ExecuteTaskInput(context=context, sandbox_id=sandbox.id)

                with pytest.raises(TaskExecutionFailedError):
                    async_to_sync(activity_environment.run)(execute_task_in_sandbox, input_data)

        finally:
            if sandbox:
                sandbox.destroy()

    @pytest.mark.django_db
    def test_execute_task_repository_not_found(self, activity_environment, github_integration):
        config = SandboxConfig(
            name="test-execute-task-no-repo",
            template=SandboxTemplate.DEFAULT_BASE,
        )

        sandbox = None
        try:
            sandbox = Sandbox.create(config)

            with patch(
                "products.tasks.backend.temporal.process_task.activities.execute_task_in_sandbox.Sandbox._get_task_command"
            ) as mock_task_cmd:
                mock_task_cmd.return_value = "ls -la"

                context = self._create_context(
                    github_integration, "PostHog/posthog-js", task_id="test-task-no-repo", run_id="test-run-no-repo"
                )
                input_data = ExecuteTaskInput(context=context, sandbox_id=sandbox.id)

                with pytest.raises(TaskExecutionFailedError):
                    async_to_sync(activity_environment.run)(execute_task_in_sandbox, input_data)

        finally:
            if sandbox:
                sandbox.destroy()

    @pytest.mark.django_db
    def test_execute_task_sandbox_not_found(self, activity_environment, github_integration):
        context = self._create_context(github_integration, "PostHog/posthog-js")
        input_data = ExecuteTaskInput(context=context, sandbox_id="non-existent-sandbox-id")

        with pytest.raises(SandboxNotFoundError):
            async_to_sync(activity_environment.run)(execute_task_in_sandbox, input_data)

    @pytest.mark.django_db
    def test_execute_task_with_different_repositories(self, activity_environment, github_integration):
        config = SandboxConfig(
            name="test-execute-different-repos",
            template=SandboxTemplate.DEFAULT_BASE,
        )

        sandbox = None
        try:
            sandbox = Sandbox.create(config)

            repos_to_test = ["PostHog/posthog-js", "PostHog/posthog.com"]

            for repo in repos_to_test:
                context = self._create_context(
                    github_integration,
                    repo,
                    task_id=f"test-task-{repo.split('/')[1]}",
                    run_id=f"test-run-{repo.split('/')[1]}",
                )
                sandbox.clone_repository(repo, github_token="")

                with patch(
                    "products.tasks.backend.temporal.process_task.activities.execute_task_in_sandbox.Sandbox._get_task_command"
                ) as mock_task_cmd:
                    mock_task_cmd.return_value = f"echo 'Working in {repo}'"

                    input_data = ExecuteTaskInput(context=context, sandbox_id=sandbox.id)

                    async_to_sync(activity_environment.run)(execute_task_in_sandbox, input_data)

                    mock_task_cmd.assert_called_once_with(
                        f"test-task-{repo.split('/')[1]}",
                        f"test-run-{repo.split('/')[1]}",
                        f"/tmp/workspace/repos/{repo.lower()}",
                        True,
                    )

        finally:
            if sandbox:
                sandbox.destroy()
