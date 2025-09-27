import os

import pytest

from products.tasks.backend.services.sandbox_agent import SandboxAgent, SandboxAgentConfig
from products.tasks.backend.services.sandbox_environment import (
    SandboxEnvironment,
    SandboxEnvironmentConfig,
    SandboxEnvironmentTemplate,
)


@pytest.mark.asyncio
class TestSandboxAgentIntegration:
    # We only run these tests when we have a Runloop API key set, we don't want to run them in CI since they create real sandbox environments and are slow.
    @pytest.fixture(scope="class", autouse=True)
    def check_api_key(self):
        if not os.environ.get("RUNLOOP_API_KEY"):
            pytest.skip("RUNLOOP_API_KEY not set, skipping integration tests")

    @pytest.fixture
    def mock_github_token(self):
        """Provide a mock GitHub token for testing."""
        return "ghp_mock_token_for_testing_12345678901234567890"

    @pytest.fixture
    def mock_posthog_credentials(self):
        """Provide mock PostHog credentials for testing."""
        return {"personal_api_key": "phx_mock_personal_api_key_123456789", "project_id": "test-project-id-123"}

    @pytest.fixture
    def public_repo_url(self):
        """Use a small public repository for testing."""
        return "https://github.com/octocat/Hello-World"

    async def test_complete_sandbox_agent_workflow(self, mock_github_token, public_repo_url, mock_posthog_credentials):
        """Comprehensive test covering agent lifecycle, repo cloning, and PostHog CLI execution."""
        sandbox_config = SandboxEnvironmentConfig(
            name="posthog-agent-test-complete", template=SandboxEnvironmentTemplate.DEFAULT_BASE
        )
        sandbox = await SandboxEnvironment.create(sandbox_config)

        agent_config = SandboxAgentConfig(
            repository_url=public_repo_url,
            github_token=mock_github_token,
            task_id="test",
            posthog_personal_api_key=mock_posthog_credentials["personal_api_key"],
            posthog_project_id=mock_posthog_credentials["project_id"],
        )

        async with await SandboxAgent.create(sandbox, agent_config) as agent:
            assert agent.id is not None
            assert agent.is_running
            assert agent.working_dir == "/tmp/workspace"
            assert agent.repository_dir == "/tmp/workspace/repo"

            setup_result = await agent.setup_repository()
            assert setup_result.exit_code == 0
            assert setup_result.error is None

            check_result = await agent.sandbox.execute("ls -la /tmp/workspace/repo")
            assert check_result.exit_code == 0
            assert ".git" in check_result.stdout

            env_check = await agent.sandbox.execute("printenv")

            assert "REPOSITORY_URL" in env_check.stdout
            assert "POSTHOG_CLI_TOKEN" in env_check.stdout
            assert "POSTHOG_CLI_ENV_ID" in env_check.stdout

            cli_result = await agent.execute_task()
            assert cli_result.exit_code == 0

            assert "posthog-cli" in cli_result.stdout.lower() or "usage" in cli_result.stdout.lower()

            context_result = await agent.sandbox.execute(f"cd {agent.repository_dir} && pwd")
            assert context_result.exit_code == 0
            assert agent.repository_dir in context_result.stdout

        assert not agent.is_running
