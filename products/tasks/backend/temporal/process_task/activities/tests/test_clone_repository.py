import os

import pytest
from unittest.mock import patch

from asgiref.sync import async_to_sync

from products.tasks.backend.services.sandbox import Sandbox, SandboxConfig, SandboxTemplate
from products.tasks.backend.temporal.exceptions import RepositoryCloneError, SandboxNotFoundError
from products.tasks.backend.temporal.process_task.activities.clone_repository import (
    CloneRepositoryInput,
    clone_repository,
)


@pytest.mark.skipif(
    not os.environ.get("MODAL_TOKEN_ID") or not os.environ.get("MODAL_TOKEN_SECRET"),
    reason="MODAL_TOKEN_ID and MODAL_TOKEN_SECRET environment variables not set",
)
class TestCloneRepositoryActivity:
    @pytest.mark.django_db
    def test_clone_repository_success_and_directory_structure(self, activity_environment, github_integration):
        config = SandboxConfig(
            name="test-clone-success-and-structure",
            template=SandboxTemplate.DEFAULT_BASE,
        )

        sandbox = None
        try:
            sandbox = Sandbox.create(config)

            input_data = CloneRepositoryInput(
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

                result = async_to_sync(activity_environment.run)(clone_repository, input_data)

                assert result is not None
                assert "posthog-js" in result

                check_result = sandbox.execute("ls -la /tmp/workspace/repos/posthog/")
                assert "posthog-js" in check_result.stdout

                git_check = sandbox.execute("cd /tmp/workspace/repos/posthog/posthog-js && git status")
                assert git_check.exit_code == 0
                assert "On branch" in git_check.stdout or "HEAD" in git_check.stdout

                structure_check = sandbox.execute("find /tmp/workspace/repos -type d | head -10")
                assert "/tmp/workspace/repos/posthog" in structure_check.stdout
                assert "/tmp/workspace/repos/posthog/posthog-js" in structure_check.stdout

                nav_check = sandbox.execute("cd /tmp/workspace/repos/posthog/posthog-js && pwd")
                assert "/tmp/workspace/repos/posthog/posthog-js" in nav_check.stdout

        finally:
            if sandbox:
                sandbox.destroy()

    @pytest.mark.django_db
    def test_clone_repository_idempotency(self, activity_environment, github_integration):
        config = SandboxConfig(
            name="test-clone-repository-idempotent",
            template=SandboxTemplate.DEFAULT_BASE,
        )

        sandbox = None
        try:
            sandbox = Sandbox.create(config)

            input_data = CloneRepositoryInput(
                sandbox_id=sandbox.id,
                repository="PostHog/posthog-js",
                github_integration_id=github_integration.id,
                task_id="test-task-idempotent",
                distinct_id="test-user-id",
            )

            with patch(
                "products.tasks.backend.temporal.process_task.activities.clone_repository.get_github_token"
            ) as mock_get_token:
                mock_get_token.return_value = ""

                result1 = async_to_sync(activity_environment.run)(clone_repository, input_data)
                assert result1 is not None

                sandbox.execute("echo 'test' > /tmp/workspace/repos/posthog/posthog-js/test_file.txt")

                check_file = sandbox.execute("cat /tmp/workspace/repos/posthog/posthog-js/test_file.txt")
                assert "test" in check_file.stdout

                result2 = async_to_sync(activity_environment.run)(clone_repository, input_data)
                assert "Cloning into 'posthog-js'" in result2 or "posthog-js" in result2

                check_file_after = sandbox.execute("ls /tmp/workspace/repos/posthog/posthog-js/test_file.txt 2>&1")
                assert (
                    "No such file" in check_file_after.stdout
                    or "No such file" in check_file_after.stderr
                    or check_file_after.exit_code != 0
                )

        finally:
            if sandbox:
                sandbox.destroy()

    @pytest.mark.django_db
    def test_clone_repository_private_repo_no_token(self, activity_environment, github_integration):
        config = SandboxConfig(
            name="test-clone-repository-auth-fail",
            template=SandboxTemplate.DEFAULT_BASE,
        )

        sandbox = None
        try:
            sandbox = Sandbox.create(config)

            input_data = CloneRepositoryInput(
                sandbox_id=sandbox.id,
                repository="PostHog/private-test-repo-that-does-not-exist",
                github_integration_id=github_integration.id,
                task_id="test-task-auth-fail",
                distinct_id="test-user-id",
            )

            with patch(
                "products.tasks.backend.temporal.process_task.activities.clone_repository.get_github_token"
            ) as mock_get_token:
                mock_get_token.return_value = "invalid-token"

                with pytest.raises(RepositoryCloneError) as exc_info:
                    async_to_sync(activity_environment.run)(clone_repository, input_data)

                assert "Git clone failed" in str(exc_info.value)

                check_result = sandbox.execute("ls /tmp/workspace/repos/posthog/ 2>&1")
                assert "private-test-repo" not in check_result.stdout

        finally:
            if sandbox:
                sandbox.destroy()

    @pytest.mark.django_db
    def test_clone_repository_multiple_repos(self, activity_environment, github_integration):
        config = SandboxConfig(
            name="test-clone-multiple-repos",
            template=SandboxTemplate.DEFAULT_BASE,
        )

        sandbox = None
        try:
            sandbox = Sandbox.create(config)

            repos = ["PostHog/posthog-js", "PostHog/posthog.com"]

            with patch(
                "products.tasks.backend.temporal.process_task.activities.clone_repository.get_github_token"
            ) as mock_get_token:
                mock_get_token.return_value = ""  # Public repos don't need auth

                for repo in repos:
                    input_data = CloneRepositoryInput(
                        sandbox_id=sandbox.id,
                        repository=repo,
                        github_integration_id=github_integration.id,
                        task_id=f"test-task-{repo.split('/')[1]}",
                        distinct_id="test-user-id",
                    )

                    result = async_to_sync(activity_environment.run)(clone_repository, input_data)
                    repo_name = repo.split("/")[1]
                    assert repo_name in result

                # Verify both repos exist
                check_result = sandbox.execute("ls /tmp/workspace/repos/posthog/")
                assert "posthog-js" in check_result.stdout
                assert "posthog.com" in check_result.stdout

                # Verify they're both git repositories
                for repo in repos:
                    repo_name = repo.split("/")[1]
                    git_check = sandbox.execute(f"cd /tmp/workspace/repos/posthog/{repo_name} && git remote -v")
                    assert git_check.exit_code == 0
                    assert "github.com" in git_check.stdout

        finally:
            if sandbox:
                sandbox.destroy()

    @pytest.mark.django_db
    def test_clone_repository_sandbox_not_found(self, activity_environment, github_integration):
        input_data = CloneRepositoryInput(
            sandbox_id="non-existent-sandbox-id",
            repository="posthog/posthog-js",
            github_integration_id=github_integration.id,
            task_id="test-task-not-found",
            distinct_id="test-user-id",
        )

        with patch(
            "products.tasks.backend.temporal.process_task.activities.clone_repository.get_github_token"
        ) as mock_get_token:
            mock_get_token.return_value = ""

            with pytest.raises(SandboxNotFoundError):
                async_to_sync(activity_environment.run)(clone_repository, input_data)
