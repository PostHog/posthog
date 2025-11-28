import os

import pytest
from unittest.mock import patch

from asgiref.sync import async_to_sync

from products.tasks.backend.services.sandbox import Sandbox, SandboxConfig, SandboxTemplate
from products.tasks.backend.temporal.exceptions import RetryableRepositorySetupError, SandboxNotFoundError
from products.tasks.backend.temporal.process_task.activities.clone_repository import (
    CloneRepositoryInput,
    clone_repository,
)
from products.tasks.backend.temporal.process_task.activities.setup_repository import (
    SetupRepositoryInput,
    setup_repository,
)


@pytest.mark.skipif(
    not os.environ.get("MODAL_TOKEN_ID") or not os.environ.get("MODAL_TOKEN_SECRET"),
    reason="MODAL_TOKEN_ID and MODAL_TOKEN_SECRET environment variables not set",
)
class TestSetupRepositoryActivity:
    @pytest.mark.django_db
    def test_setup_repository_success(self, activity_environment, github_integration):
        config = SandboxConfig(
            name="test-setup-repository",
            template=SandboxTemplate.DEFAULT_BASE,
        )

        sandbox = None
        try:
            sandbox = Sandbox.create(config)

            clone_input = CloneRepositoryInput(
                sandbox_id=sandbox.id,
                repository="posthog/posthog-js",
                github_integration_id=github_integration.id,
                task_id="test-task-123",
                run_id="test-run-456",
                distinct_id="test-user-id",
            )

            with patch(
                "products.tasks.backend.temporal.process_task.activities.clone_repository.get_github_token"
            ) as mock_get_token:
                mock_get_token.return_value = ""
                async_to_sync(activity_environment.run)(clone_repository, clone_input)

            with patch(
                "products.tasks.backend.temporal.process_task.activities.setup_repository.Sandbox._get_setup_command"
            ) as mock_setup_cmd:
                mock_setup_cmd.return_value = (
                    "git config user.email 'test@example.com' && "
                    "git config user.name 'Test User' && "
                    "echo 'hello world' > test_setup.txt && "
                    "git add test_setup.txt && "
                    "git commit -m 'test setup'"
                )

                setup_input = SetupRepositoryInput(
                    sandbox_id=sandbox.id,
                    repository="posthog/posthog-js",
                    task_id="test-task-123",
                    distinct_id="test-user-id",
                )

                result = async_to_sync(activity_environment.run)(setup_repository, setup_input)

                assert result is not None

            check_file = sandbox.execute("cat /tmp/workspace/repos/posthog/posthog-js/test_setup.txt")
            assert "hello world" in check_file.stdout

        finally:
            if sandbox:
                sandbox.destroy()

    @pytest.mark.django_db
    def test_setup_repository_without_clone(self, activity_environment):
        config = SandboxConfig(
            name="test-setup-no-clone",
            template=SandboxTemplate.DEFAULT_BASE,
        )

        sandbox = None
        try:
            sandbox = Sandbox.create(config)

            setup_input = SetupRepositoryInput(
                sandbox_id=sandbox.id,
                repository="posthog/posthog-js",
                task_id="test-task-no-clone",
                distinct_id="test-user-id",
            )

            with pytest.raises(RetryableRepositorySetupError):
                async_to_sync(activity_environment.run)(setup_repository, setup_input)
        finally:
            if sandbox:
                sandbox.destroy()

    @pytest.mark.django_db
    def test_setup_repository_sandbox_not_found(self, activity_environment):
        setup_input = SetupRepositoryInput(
            sandbox_id="non-existent-sandbox-id",
            repository="posthog/posthog-js",
            task_id="test-task-not-found",
            distinct_id="test-user-id",
        )

        with pytest.raises(SandboxNotFoundError):
            async_to_sync(activity_environment.run)(setup_repository, setup_input)

    @pytest.mark.django_db
    def test_setup_repository_fails_with_uncommitted_changes(self, activity_environment, github_integration):
        config = SandboxConfig(
            name="test-setup-uncommitted",
            template=SandboxTemplate.DEFAULT_BASE,
        )

        sandbox = None
        try:
            sandbox = Sandbox.create(config)

            clone_input = CloneRepositoryInput(
                sandbox_id=sandbox.id,
                repository="posthog/posthog-js",
                github_integration_id=github_integration.id,
                task_id="test-task-uncommitted",
                run_id="test-run-uncommitted",
                distinct_id="test-user-id",
            )

            with patch(
                "products.tasks.backend.temporal.process_task.activities.clone_repository.get_github_token"
            ) as mock_get_token:
                mock_get_token.return_value = ""
                async_to_sync(activity_environment.run)(clone_repository, clone_input)

            with patch(
                "products.tasks.backend.temporal.process_task.activities.setup_repository.Sandbox._get_setup_command"
            ) as mock_setup_cmd:
                mock_setup_cmd.return_value = "pnpm install && echo 'test' > uncommitted_file.txt"

                setup_input = SetupRepositoryInput(
                    sandbox_id=sandbox.id,
                    repository="posthog/posthog-js",
                    task_id="test-task-uncommitted",
                    distinct_id="test-user-id",
                )

                with pytest.raises(RetryableRepositorySetupError) as exc_info:
                    async_to_sync(activity_environment.run)(setup_repository, setup_input)

                assert "uncommitted changes" in str(exc_info.value).lower()
                assert "uncommitted_file.txt" in exc_info.value.context.get("uncommitted_changes", "")

        finally:
            if sandbox:
                sandbox.destroy()
