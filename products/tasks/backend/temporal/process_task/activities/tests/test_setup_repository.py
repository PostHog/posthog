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
        config = SandboxEnvironmentConfig(
            name="test-setup-repository",
            template=SandboxEnvironmentTemplate.DEFAULT_BASE,
        )

        sandbox = None
        try:
            sandbox = await SandboxEnvironment.create(config)

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

            # Check that node_modules doesn't exist before setup
            check_before = await sandbox.execute(
                "ls -la /tmp/workspace/repos/posthog/posthog-js/ | grep node_modules || echo 'no node_modules'"
            )
            assert "no node_modules" in check_before.stdout

            # Mock the _get_setup_command inside the setup_repository activity to just run pnpm install
            with patch(
                "products.tasks.backend.temporal.process_task.activities.setup_repository.SandboxAgent._get_setup_command"
            ) as mock_setup_cmd:
                mock_setup_cmd.return_value = "pnpm install"

                setup_input = SetupRepositoryInput(
                    sandbox_id=sandbox.id,
                    repository="PostHog/posthog-js",
                )

                result = await activity_environment.run(setup_repository, setup_input)

                assert result is not None

            # Verify node_modules exists after setup
            check_after = await sandbox.execute(
                "ls -la /tmp/workspace/repos/posthog/posthog-js/ | grep node_modules || echo 'no node_modules'"
            )
            assert "node_modules" in check_after.stdout
            assert "no node_modules" not in check_after.stdout

        finally:
            if sandbox:
                await sandbox.destroy()

    @pytest.mark.asyncio
    @pytest.mark.django_db
    async def test_setup_repository_without_clone(self, activity_environment):
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
        setup_input = SetupRepositoryInput(
            sandbox_id="non-existent-sandbox-id",
            repository="PostHog/posthog-js",
        )

        with pytest.raises(Exception) as exc_info:
            await activity_environment.run(setup_repository, setup_input)

        assert "not found" in str(exc_info.value).lower() or "Failed to retrieve sandbox" in str(exc_info.value)
