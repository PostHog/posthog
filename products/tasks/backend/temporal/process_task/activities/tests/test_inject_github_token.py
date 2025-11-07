import os

import pytest
from unittest.mock import patch

from products.tasks.backend.services.sandbox import Sandbox, SandboxConfig, SandboxTemplate
from products.tasks.backend.temporal.exceptions import SandboxNotFoundError
from products.tasks.backend.temporal.process_task.activities.inject_github_token import (
    InjectGitHubTokenInput,
    inject_github_token,
)


@pytest.mark.skipif(not os.environ.get("RUNLOOP_API_KEY"), reason="RUNLOOP_API_KEY environment variable not set")
class TestInjectGitHubTokenActivity:
    @pytest.mark.asyncio
    @pytest.mark.django_db
    async def test_inject_github_token_success(self, activity_environment, github_integration):
        config = SandboxConfig(
            name="test-inject-token-success",
            template=SandboxTemplate.DEFAULT_BASE,
        )

        sandbox = None
        try:
            sandbox = await Sandbox.create(config)

            input_data = InjectGitHubTokenInput(
                sandbox_id=sandbox.id,
                github_integration_id=github_integration.id,
                task_id="test-task-123",
                distinct_id="test-user-id",
            )

            test_token = "ghp_test_token_12345"

            with patch(
                "products.tasks.backend.temporal.process_task.activities.inject_github_token.get_github_token"
            ) as mock_get_token:
                mock_get_token.return_value = test_token

                await activity_environment.run(inject_github_token, input_data)

                check_result = await sandbox.execute("bash -c 'source ~/.bashrc && echo $GITHUB_TOKEN'")
                assert check_result.exit_code == 0
                assert test_token in check_result.stdout

        finally:
            if sandbox:
                await sandbox.destroy()

    @pytest.mark.asyncio
    @pytest.mark.django_db
    async def test_inject_github_token_sandbox_not_found(self, activity_environment, github_integration):
        input_data = InjectGitHubTokenInput(
            sandbox_id="non-existent-sandbox-id",
            github_integration_id=github_integration.id,
            task_id="test-task-not-found",
            distinct_id="test-user-id",
        )

        with patch(
            "products.tasks.backend.temporal.process_task.activities.inject_github_token.get_github_token"
        ) as mock_get_token:
            mock_get_token.return_value = "test_token"

            with pytest.raises(SandboxNotFoundError):
                await activity_environment.run(inject_github_token, input_data)
