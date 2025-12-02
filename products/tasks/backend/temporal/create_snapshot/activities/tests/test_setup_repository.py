import os

import pytest
from unittest.mock import patch

from asgiref.sync import async_to_sync

from products.tasks.backend.services.sandbox import Sandbox, SandboxConfig, SandboxTemplate
from products.tasks.backend.temporal.create_snapshot.activities.clone_repository import (
    CloneRepositoryInput,
    clone_repository,
)
from products.tasks.backend.temporal.create_snapshot.activities.get_snapshot_context import SnapshotContext
from products.tasks.backend.temporal.create_snapshot.activities.setup_repository import (
    SetupRepositoryInput,
    setup_repository,
)
from products.tasks.backend.temporal.exceptions import RetryableRepositorySetupError, SandboxNotFoundError


@pytest.mark.skipif(
    not os.environ.get("MODAL_TOKEN_ID") or not os.environ.get("MODAL_TOKEN_SECRET"),
    reason="MODAL_TOKEN_ID and MODAL_TOKEN_SECRET environment variables not set",
)
class TestSetupRepositoryActivity:
    def _create_context(self, github_integration, repository) -> SnapshotContext:
        return SnapshotContext(
            github_integration_id=github_integration.id,
            repository=repository,
            team_id=github_integration.team_id,
        )

    @pytest.mark.django_db
    def test_setup_repository_success(self, activity_environment, github_integration):
        config = SandboxConfig(
            name="test-snapshot-setup-repository",
            template=SandboxTemplate.DEFAULT_BASE,
        )

        sandbox = None
        try:
            sandbox = Sandbox.create(config)
            context = self._create_context(github_integration, "posthog/posthog-js")

            clone_input = CloneRepositoryInput(context=context, sandbox_id=sandbox.id)

            with patch(
                "products.tasks.backend.temporal.create_snapshot.activities.clone_repository.get_github_token"
            ) as mock_get_token:
                mock_get_token.return_value = ""
                async_to_sync(activity_environment.run)(clone_repository, clone_input)

            with patch(
                "products.tasks.backend.temporal.create_snapshot.activities.setup_repository.Sandbox._get_setup_command"
            ) as mock_setup_cmd:
                mock_setup_cmd.return_value = (
                    "git config user.email 'test@example.com' && "
                    "git config user.name 'Test User' && "
                    "echo 'hello world' > test_setup.txt && "
                    "git add test_setup.txt && "
                    "git commit -m 'test setup'"
                )

                setup_input = SetupRepositoryInput(context=context, sandbox_id=sandbox.id)

                result = async_to_sync(activity_environment.run)(setup_repository, setup_input)

                assert result is not None

            check_file = sandbox.execute("cat /tmp/workspace/repos/posthog/posthog-js/test_setup.txt")
            assert "hello world" in check_file.stdout

        finally:
            if sandbox:
                sandbox.destroy()

    @pytest.mark.django_db
    def test_setup_repository_without_clone(self, activity_environment, github_integration):
        config = SandboxConfig(
            name="test-snapshot-setup-no-clone",
            template=SandboxTemplate.DEFAULT_BASE,
        )

        sandbox = None
        try:
            sandbox = Sandbox.create(config)
            context = self._create_context(github_integration, "posthog/posthog-js")
            setup_input = SetupRepositoryInput(context=context, sandbox_id=sandbox.id)

            with pytest.raises(RetryableRepositorySetupError):
                async_to_sync(activity_environment.run)(setup_repository, setup_input)
        finally:
            if sandbox:
                sandbox.destroy()

    @pytest.mark.django_db
    def test_setup_repository_sandbox_not_found(self, activity_environment, github_integration):
        context = self._create_context(github_integration, "posthog/posthog-js")
        setup_input = SetupRepositoryInput(context=context, sandbox_id="non-existent-sandbox-id")

        with pytest.raises(SandboxNotFoundError):
            async_to_sync(activity_environment.run)(setup_repository, setup_input)

    @pytest.mark.django_db
    def test_setup_repository_fails_with_uncommitted_changes(self, activity_environment, github_integration):
        config = SandboxConfig(
            name="test-snapshot-setup-uncommitted",
            template=SandboxTemplate.DEFAULT_BASE,
        )

        sandbox = None
        try:
            sandbox = Sandbox.create(config)
            context = self._create_context(github_integration, "posthog/posthog-js")

            clone_input = CloneRepositoryInput(context=context, sandbox_id=sandbox.id)

            with patch(
                "products.tasks.backend.temporal.create_snapshot.activities.clone_repository.get_github_token"
            ) as mock_get_token:
                mock_get_token.return_value = ""
                async_to_sync(activity_environment.run)(clone_repository, clone_input)

            with patch(
                "products.tasks.backend.temporal.create_snapshot.activities.setup_repository.Sandbox._get_setup_command"
            ) as mock_setup_cmd:
                mock_setup_cmd.return_value = "pnpm install && echo 'test' > uncommitted_file.txt"

                setup_input = SetupRepositoryInput(context=context, sandbox_id=sandbox.id)

                with pytest.raises(RetryableRepositorySetupError) as exc_info:
                    async_to_sync(activity_environment.run)(setup_repository, setup_input)

                assert "uncommitted changes" in str(exc_info.value).lower()

        finally:
            if sandbox:
                sandbox.destroy()
