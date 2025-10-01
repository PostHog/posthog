import os

import pytest
from unittest.mock import patch

from products.tasks.backend.services.sandbox_environment import (
    SandboxEnvironment,
    SandboxEnvironmentConfig,
    SandboxEnvironmentTemplate,
)
from products.tasks.backend.temporal.process_task.activities.clone_repository import (
    CloneRepositoryInput,
    clone_repository,
)
from products.tasks.backend.temporal.process_task.activities.setup_repository import (
    SetupRepositoryInput,
    setup_repository,
)


@pytest.mark.skipif(not os.environ.get("RUNLOOP_API_KEY"), reason="RUNLOOP_API_KEY environment variable not set")
class TestSetupRepositoryActivity:
    @pytest.mark.asyncio
    @pytest.mark.django_db
    async def test_setup_repository_success(self, activity_environment, github_integration):
        """Test successful repository setup after cloning."""
        config = SandboxEnvironmentConfig(
            name="test-setup-repository",
            template=SandboxEnvironmentTemplate.DEFAULT_BASE,
        )

        sandbox = None
        try:
            sandbox = await SandboxEnvironment.create(config)

            # First clone the repository
            clone_input = CloneRepositoryInput(
                sandbox_id=sandbox.id,
                repository="PostHog/posthog-js",
                github_integration_id=github_integration.id,
            )

            with patch(
                "products.tasks.backend.temporal.process_task.activities.clone_repository.get_github_token"
            ) as mock_get_token:
                mock_get_token.return_value = ""  # Public repo doesn't need auth
                await activity_environment.run(clone_repository, clone_input)

            # Now run setup on the cloned repository
            setup_input = SetupRepositoryInput(
                sandbox_id=sandbox.id,
                repository="PostHog/posthog-js",
            )

            result = await activity_environment.run(setup_repository, setup_input)

            # Setup should return output
            assert result is not None

            # Verify the repository still exists after setup
            check_result = await sandbox.execute("ls -la /tmp/workspace/repos/posthog/")
            assert "posthog-js" in check_result.stdout

        finally:
            if sandbox:
                await sandbox.destroy()

    @pytest.mark.asyncio
    @pytest.mark.django_db
    async def test_setup_repository_without_clone(self, activity_environment, github_integration):
        """Test that setup fails if repository hasn't been cloned first."""
        config = SandboxEnvironmentConfig(
            name="test-setup-no-clone",
            template=SandboxEnvironmentTemplate.DEFAULT_BASE,
        )

        sandbox = None
        try:
            sandbox = await SandboxEnvironment.create(config)

            # Try to setup without cloning first
            setup_input = SetupRepositoryInput(
                sandbox_id=sandbox.id,
                repository="PostHog/posthog-js",
            )

            with pytest.raises(RuntimeError) as exc_info:
                await activity_environment.run(setup_repository, setup_input)

            assert "does not exist" in str(exc_info.value) or "Failed to setup repository" in str(exc_info.value)

        finally:
            if sandbox:
                await sandbox.destroy()

    @pytest.mark.asyncio
    @pytest.mark.django_db
    async def test_setup_repository_sandbox_not_found(self, activity_environment):
        """Test that setup fails with invalid sandbox ID."""
        setup_input = SetupRepositoryInput(
            sandbox_id="non-existent-sandbox-id",
            repository="PostHog/posthog-js",
        )

        with pytest.raises(Exception) as exc_info:
            await activity_environment.run(setup_repository, setup_input)

        assert "not found" in str(exc_info.value).lower() or "Failed to retrieve sandbox" in str(exc_info.value)

    @pytest.mark.asyncio
    @pytest.mark.django_db
    async def test_setup_repository_multiple_repos(self, activity_environment, github_integration):
        """Test setting up multiple repositories in the same sandbox."""
        config = SandboxEnvironmentConfig(
            name="test-setup-multiple",
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

                # Clone and setup each repository
                for repo in repos:
                    # Clone
                    clone_input = CloneRepositoryInput(
                        sandbox_id=sandbox.id,
                        repository=repo,
                        github_integration_id=github_integration.id,
                    )
                    await activity_environment.run(clone_repository, clone_input)

                    # Setup
                    setup_input = SetupRepositoryInput(
                        sandbox_id=sandbox.id,
                        repository=repo,
                    )
                    result = await activity_environment.run(setup_repository, setup_input)
                    assert result is not None

                # Verify both repos still exist
                check_result = await sandbox.execute("ls /tmp/workspace/repos/posthog/")
                assert "posthog-js" in check_result.stdout
                assert "posthog.com" in check_result.stdout

        finally:
            if sandbox:
                await sandbox.destroy()
