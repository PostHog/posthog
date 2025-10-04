import os

import pytest
from unittest.mock import patch

from products.tasks.backend.services.sandbox_environment import (
    SandboxEnvironment,
    SandboxEnvironmentConfig,
    SandboxEnvironmentTemplate,
)
from products.tasks.backend.temporal.exceptions import RepositoryCloneError, SandboxNotFoundError
from products.tasks.backend.temporal.process_task.activities.clone_repository import (
    CloneRepositoryInput,
    clone_repository,
)


@pytest.mark.skipif(not os.environ.get("RUNLOOP_API_KEY"), reason="RUNLOOP_API_KEY environment variable not set")
class TestCloneRepositoryActivity:
    @pytest.mark.asyncio
    @pytest.mark.django_db
    async def test_clone_repository_success_and_directory_structure(self, activity_environment, github_integration):
        config = SandboxEnvironmentConfig(
            name="test-clone-success-and-structure",
            template=SandboxEnvironmentTemplate.DEFAULT_BASE,
        )

        sandbox = None
        try:
            sandbox = await SandboxEnvironment.create(config)

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

                result = await activity_environment.run(clone_repository, input_data)

                # Verify we got output (git clone outputs to stderr)
                assert result is not None
                assert "posthog-js" in result

                # Verify the repository actually exists in the sandbox
                check_result = await sandbox.execute("ls -la /tmp/workspace/repos/posthog/")
                assert "posthog-js" in check_result.stdout

                # Verify it's a git repository
                git_check = await sandbox.execute("cd /tmp/workspace/repos/posthog/posthog-js && git status")
                assert git_check.exit_code == 0
                assert "On branch" in git_check.stdout or "HEAD" in git_check.stdout

                # Verify directory structure is correct
                structure_check = await sandbox.execute("find /tmp/workspace/repos -type d | head -10")
                assert "/tmp/workspace/repos/posthog" in structure_check.stdout
                assert "/tmp/workspace/repos/posthog/posthog-js" in structure_check.stdout

                # Verify we can navigate the structure
                nav_check = await sandbox.execute("cd /tmp/workspace/repos/posthog/posthog-js && pwd")
                assert "/tmp/workspace/repos/posthog/posthog-js" in nav_check.stdout

        finally:
            if sandbox:
                await sandbox.destroy()

    @pytest.mark.asyncio
    @pytest.mark.django_db
    async def test_clone_repository_idempotency(self, activity_environment, github_integration):
        config = SandboxEnvironmentConfig(
            name="test-clone-repository-idempotent",
            template=SandboxEnvironmentTemplate.DEFAULT_BASE,
        )

        sandbox = None
        try:
            sandbox = await SandboxEnvironment.create(config)

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

                # First clone
                result1 = await activity_environment.run(clone_repository, input_data)
                assert result1 is not None

                # Create a file to verify it gets wiped
                await sandbox.execute("echo 'test' > /tmp/workspace/repos/posthog/posthog-js/test_file.txt")

                # Verify file exists
                check_file = await sandbox.execute("cat /tmp/workspace/repos/posthog/posthog-js/test_file.txt")
                assert "test" in check_file.stdout

                # Second clone (should wipe and re-clone)
                result2 = await activity_environment.run(clone_repository, input_data)
                assert "Cloning into 'posthog-js'" in result2 or "posthog-js" in result2

                # Verify test file was removed (proving idempotency)
                check_file_after = await sandbox.execute(
                    "ls /tmp/workspace/repos/posthog/posthog-js/test_file.txt 2>&1"
                )
                assert (
                    "No such file" in check_file_after.stdout
                    or "No such file" in check_file_after.stderr
                    or check_file_after.exit_code != 0
                )

        finally:
            if sandbox:
                await sandbox.destroy()

    @pytest.mark.asyncio
    @pytest.mark.django_db
    async def test_clone_repository_private_repo_no_token(self, activity_environment, github_integration):
        config = SandboxEnvironmentConfig(
            name="test-clone-repository-auth-fail",
            template=SandboxEnvironmentTemplate.DEFAULT_BASE,
        )

        sandbox = None
        try:
            sandbox = await SandboxEnvironment.create(config)

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
                    await activity_environment.run(clone_repository, input_data)

                assert "Git clone failed" in str(exc_info.value)

                # Verify repository doesn't exist
                check_result = await sandbox.execute("ls /tmp/workspace/repos/posthog/ 2>&1")
                assert "private-test-repo" not in check_result.stdout

        finally:
            if sandbox:
                await sandbox.destroy()

    @pytest.mark.asyncio
    @pytest.mark.django_db
    async def test_clone_repository_multiple_repos(self, activity_environment, github_integration):
        config = SandboxEnvironmentConfig(
            name="test-clone-multiple-repos",
            template=SandboxEnvironmentTemplate.DEFAULT_BASE,
        )

        sandbox = None
        try:
            sandbox = await SandboxEnvironment.create(config)

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

                    result = await activity_environment.run(clone_repository, input_data)
                    repo_name = repo.split("/")[1]
                    assert repo_name in result

                # Verify both repos exist
                check_result = await sandbox.execute("ls /tmp/workspace/repos/posthog/")
                assert "posthog-js" in check_result.stdout
                assert "posthog.com" in check_result.stdout

                # Verify they're both git repositories
                for repo in repos:
                    repo_name = repo.split("/")[1]
                    git_check = await sandbox.execute(f"cd /tmp/workspace/repos/posthog/{repo_name} && git remote -v")
                    assert git_check.exit_code == 0
                    assert "github.com" in git_check.stdout

        finally:
            if sandbox:
                await sandbox.destroy()

    @pytest.mark.asyncio
    @pytest.mark.django_db
    async def test_clone_repository_sandbox_not_found(self, activity_environment, github_integration):
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
                await activity_environment.run(clone_repository, input_data)
