import os

import pytest

from asgiref.sync import async_to_sync

from products.tasks.backend.services.sandbox import Sandbox, SandboxConfig, SandboxTemplate
from products.tasks.backend.temporal.create_snapshot.activities.get_snapshot_context import SnapshotContext
from products.tasks.backend.temporal.create_snapshot.activities.setup_repository import (
    SetupRepositoryInput,
    setup_repository,
)
from products.tasks.backend.temporal.exceptions import SandboxNotFoundError


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
    def test_setup_repository_returns_success(self, activity_environment, github_integration):
        """setup_repository is now a no-op that returns success (setup happens via agent-server)."""
        config = SandboxConfig(
            name="test-snapshot-setup-repository",
            template=SandboxTemplate.DEFAULT_BASE,
        )

        sandbox = None
        try:
            sandbox = Sandbox.create(config)
            context = self._create_context(github_integration, "posthog/posthog-js")

            setup_input = SetupRepositoryInput(context=context, sandbox_id=sandbox.id)
            result = async_to_sync(activity_environment.run)(setup_repository, setup_input)

            assert result is not None

        finally:
            if sandbox:
                sandbox.destroy()

    @pytest.mark.django_db
    def test_setup_repository_sandbox_not_found(self, activity_environment, github_integration):
        context = self._create_context(github_integration, "posthog/posthog-js")
        setup_input = SetupRepositoryInput(context=context, sandbox_id="non-existent-sandbox-id")

        with pytest.raises(SandboxNotFoundError):
            async_to_sync(activity_environment.run)(setup_repository, setup_input)
