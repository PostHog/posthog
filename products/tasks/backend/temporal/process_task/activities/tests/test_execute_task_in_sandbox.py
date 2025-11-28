import os

import pytest
from unittest.mock import patch

from asgiref.sync import async_to_sync

from products.tasks.backend.services.sandbox import Sandbox, SandboxConfig, SandboxTemplate
from products.tasks.backend.temporal.exceptions import SandboxNotFoundError, TaskExecutionFailedError
from products.tasks.backend.temporal.process_task.activities.clone_repository import (
    CloneRepositoryInput,
    clone_repository,
)
from products.tasks.backend.temporal.process_task.activities.execute_task_in_sandbox import (
    ExecuteTaskInput,
    execute_task_in_sandbox,
)


@pytest.mark.skipif(
    not os.environ.get("MODAL_TOKEN_ID") or not os.environ.get("MODAL_TOKEN_SECRET"),
    reason="MODAL_TOKEN_ID and MODAL_TOKEN_SECRET environment variables not set",
)
class TestExecuteTaskInSandboxActivity:
    @pytest.mark.django_db
    def test_execute_task_success(self, activity_environment, github_integration):
        config = SandboxConfig(
            name="test-execute-task",
            template=SandboxTemplate.DEFAULT_BASE,
        )

        sandbox = None
        try:
            sandbox = Sandbox.create(config)

            clone_input = CloneRepositoryInput(
                sandbox_id=sandbox.id,
                repository="PostHog/posthog-js",
                github_integration_id=github_integration.id,
                task_id="test-task-123",
                distinct_id="test-user-id",
            )

            with patch(
                "products.tasks.backend.temporal.process_task.activities.clone_repository.get_github_token"
            ) as mock_get_token:
                mock_get_token.return_value = ""
                async_to_sync(activity_environment.run)(clone_repository, clone_input)

            with patch(
                "products.tasks.backend.temporal.process_task.activities.execute_task_in_sandbox.Sandbox._get_task_command"
            ) as mock_task_cmd:
                mock_task_cmd.return_value = "echo 'Task executed successfully'"

                input_data = ExecuteTaskInput(
                    sandbox_id=sandbox.id,
                    task_id="test-task-123",
                    repository="PostHog/posthog-js",
                    distinct_id="test-user-id",
                )

                async_to_sync(activity_environment.run)(execute_task_in_sandbox, input_data)

                mock_task_cmd.assert_called_once_with("test-task-123", "/tmp/workspace/repos/posthog/posthog-js")

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

            clone_input = CloneRepositoryInput(
                sandbox_id=sandbox.id,
                repository="PostHog/posthog-js",
                github_integration_id=github_integration.id,
                task_id="test-task-fail",
                distinct_id="test-user-id",
            )

            with patch(
                "products.tasks.backend.temporal.process_task.activities.clone_repository.get_github_token"
            ) as mock_get_token:
                mock_get_token.return_value = ""
                async_to_sync(activity_environment.run)(clone_repository, clone_input)

            with patch(
                "products.tasks.backend.temporal.process_task.activities.execute_task_in_sandbox.Sandbox._get_task_command"
            ) as mock_task_cmd:
                mock_task_cmd.return_value = "exit 1"

                input_data = ExecuteTaskInput(
                    sandbox_id=sandbox.id,
                    task_id="test-task-fail",
                    repository="PostHog/posthog-js",
                    distinct_id="test-user-id",
                )

                with pytest.raises(TaskExecutionFailedError):
                    async_to_sync(activity_environment.run)(execute_task_in_sandbox, input_data)

        finally:
            if sandbox:
                sandbox.destroy()

    @pytest.mark.django_db
    def test_execute_task_repository_not_found(self, activity_environment):
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

                input_data = ExecuteTaskInput(
                    sandbox_id=sandbox.id,
                    task_id="test-task-no-repo",
                    repository="PostHog/posthog-js",
                    distinct_id="test-user-id",
                )

                with pytest.raises(TaskExecutionFailedError):
                    async_to_sync(activity_environment.run)(execute_task_in_sandbox, input_data)

        finally:
            if sandbox:
                sandbox.destroy()

    @pytest.mark.django_db
    def test_execute_task_sandbox_not_found(self, activity_environment):
        input_data = ExecuteTaskInput(
            sandbox_id="non-existent-sandbox-id",
            task_id="test-task",
            repository="PostHog/posthog-js",
            distinct_id="test-user-id",
        )

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

            with patch(
                "products.tasks.backend.temporal.process_task.activities.clone_repository.get_github_token"
            ) as mock_get_token:
                mock_get_token.return_value = ""

                for repo in repos_to_test:
                    clone_input = CloneRepositoryInput(
                        sandbox_id=sandbox.id,
                        repository=repo,
                        github_integration_id=github_integration.id,
                        task_id=f"test-task-{repo.split('/')[1]}",
                        distinct_id="test-user-id",
                    )
                    async_to_sync(activity_environment.run)(clone_repository, clone_input)

                    with patch(
                        "products.tasks.backend.temporal.process_task.activities.execute_task_in_sandbox.Sandbox._get_task_command"
                    ) as mock_task_cmd:
                        mock_task_cmd.return_value = f"echo 'Working in {repo}'"

                        input_data = ExecuteTaskInput(
                            sandbox_id=sandbox.id,
                            task_id=f"test-task-{repo.split('/')[1]}",
                            repository=repo,
                            distinct_id="test-user-id",
                        )

                        async_to_sync(activity_environment.run)(execute_task_in_sandbox, input_data)

                        mock_task_cmd.assert_called_once_with(
                            f"test-task-{repo.split('/')[1]}",
                            f"/tmp/workspace/repos/{repo.lower()}",
                        )

        finally:
            if sandbox:
                sandbox.destroy()
