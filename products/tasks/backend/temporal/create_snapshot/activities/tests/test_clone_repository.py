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
from products.tasks.backend.temporal.exceptions import RepositoryCloneError, SandboxNotFoundError


@pytest.mark.skipif(
    not os.environ.get("MODAL_TOKEN_ID") or not os.environ.get("MODAL_TOKEN_SECRET"),
    reason="MODAL_TOKEN_ID and MODAL_TOKEN_SECRET environment variables not set",
)
class TestCloneRepositoryActivity:
    def _create_context(self, github_integration, repository) -> SnapshotContext:
        return SnapshotContext(
            github_integration_id=github_integration.id,
            repository=repository,
            team_id=github_integration.team_id,
        )

    @pytest.mark.django_db
    def test_clone_repository_success(self, activity_environment, github_integration):
        config = SandboxConfig(
            name="test-snapshot-clone-success",
            template=SandboxTemplate.DEFAULT_BASE,
        )

        sandbox = None
        try:
            sandbox = Sandbox.create(config)
            context = self._create_context(github_integration, "PostHog/posthog-js")
            input_data = CloneRepositoryInput(context=context, sandbox_id=sandbox.id)

            with patch(
                "products.tasks.backend.temporal.create_snapshot.activities.clone_repository.get_github_token"
            ) as mock_get_token:
                mock_get_token.return_value = ""

                result = async_to_sync(activity_environment.run)(clone_repository, input_data)

                assert result is not None
                assert "posthog-js" in result

                check_result = sandbox.execute("ls -la /tmp/workspace/repos/posthog/")
                assert "posthog-js" in check_result.stdout

        finally:
            if sandbox:
                sandbox.destroy()

    @pytest.mark.django_db
    def test_clone_repository_idempotency(self, activity_environment, github_integration):
        config = SandboxConfig(
            name="test-snapshot-clone-idempotent",
            template=SandboxTemplate.DEFAULT_BASE,
        )

        sandbox = None
        try:
            sandbox = Sandbox.create(config)
            context = self._create_context(github_integration, "PostHog/posthog-js")
            input_data = CloneRepositoryInput(context=context, sandbox_id=sandbox.id)

            with patch(
                "products.tasks.backend.temporal.create_snapshot.activities.clone_repository.get_github_token"
            ) as mock_get_token:
                mock_get_token.return_value = ""

                result1 = async_to_sync(activity_environment.run)(clone_repository, input_data)
                assert result1 is not None

                sandbox.execute("echo 'test' > /tmp/workspace/repos/posthog/posthog-js/test_file.txt")

                result2 = async_to_sync(activity_environment.run)(clone_repository, input_data)
                assert result2 is not None

                check_file = sandbox.execute("ls /tmp/workspace/repos/posthog/posthog-js/test_file.txt 2>&1")
                assert "No such file" in check_file.stdout or check_file.exit_code != 0

        finally:
            if sandbox:
                sandbox.destroy()

    @pytest.mark.django_db
    def test_clone_repository_nonexistent_repo(self, activity_environment, github_integration):
        config = SandboxConfig(
            name="test-snapshot-clone-nonexistent",
            template=SandboxTemplate.DEFAULT_BASE,
        )

        sandbox = None
        try:
            sandbox = Sandbox.create(config)
            context = self._create_context(github_integration, "PostHog/nonexistent-repo-12345")
            input_data = CloneRepositoryInput(context=context, sandbox_id=sandbox.id)

            with patch(
                "products.tasks.backend.temporal.create_snapshot.activities.clone_repository.get_github_token"
            ) as mock_get_token:
                mock_get_token.return_value = ""

                with pytest.raises(RepositoryCloneError):
                    async_to_sync(activity_environment.run)(clone_repository, input_data)

        finally:
            if sandbox:
                sandbox.destroy()

    @pytest.mark.django_db
    def test_clone_repository_sandbox_not_found(self, activity_environment, github_integration):
        context = self._create_context(github_integration, "posthog/posthog-js")
        input_data = CloneRepositoryInput(context=context, sandbox_id="non-existent-sandbox-id")

        with patch(
            "products.tasks.backend.temporal.create_snapshot.activities.clone_repository.get_github_token"
        ) as mock_get_token:
            mock_get_token.return_value = ""

            with pytest.raises(SandboxNotFoundError):
                async_to_sync(activity_environment.run)(clone_repository, input_data)
