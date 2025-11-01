import shlex
import logging
from dataclasses import dataclass
from typing import Optional

from products.tasks.backend.services.sandbox_environment import (
    ExecutionResult,
    SandboxEnvironment,
    SandboxEnvironmentConfig,
    SandboxEnvironmentTemplate,
)
from products.tasks.backend.temporal.process_task.utils import get_github_token

logger = logging.getLogger(__name__)


@dataclass
class AgentExecutionConfig:
    """
    Configuration for running the agent in a sandbox.

    Args:
        prompt: The instruction/task for the agent to execute
        repository: Repository in format "organization/repository" (e.g., "posthog/posthog")
        github_integration_id: ID of the GitHub integration to use for authentication
        max_turns: Maximum number of conversation turns for the agent (default: 20)
        timeout_seconds: Maximum execution time in seconds (default: 20 minutes)
        posthog_api_url: PostHog API URL for telemetry (default: "https://app.posthog.com")
        posthog_api_key: PostHog API key for telemetry (optional)
        sandbox_name: Custom name for the sandbox (optional, auto-generated if not provided)
    """

    prompt: str
    repository: str
    github_integration_id: int
    max_turns: int = 20
    timeout_seconds: int = 20 * 60  # 20 minutes
    posthog_api_url: str = "https://app.posthog.com"
    posthog_api_key: Optional[str] = None
    sandbox_name: Optional[str] = None


async def run_agent_with_prompt(config: AgentExecutionConfig) -> ExecutionResult:
    """
    Run the PostHog agent in a Runloop sandbox with a custom prompt.

    This function handles the complete lifecycle:
    1. Creates a Runloop sandbox environment
    2. Clones the specified repository
    3. Runs the agent with your custom prompt
    4. Cleans up the sandbox (always, even on failure)

    Usage:
        ```python
        from products.tasks.backend.services.run_agent_in_sandbox import (
            run_agent_with_prompt,
            AgentExecutionConfig,
        )

        result = await run_agent_with_prompt(AgentExecutionConfig(
            prompt="Add type hints to all functions in the auth module",
            repository="posthog/posthog",
            github_integration_id=integration.id,
            posthog_api_key=user.personal_api_key,
        ))

        if result.exit_code == 0:
            print("Success!", result.stdout)
        else:
            print("Failed:", result.stderr)
        ```

    Args:
        config: Configuration object containing all parameters for the execution

    Returns:
        ExecutionResult: Contains stdout, stderr, exit_code, and optional error message

    Raises:
        Exception: Any errors during sandbox creation, repository cloning, or agent execution
    """
    org, repo = config.repository.lower().split("/")
    repo_path = f"/tmp/workspace/repos/{org}/{repo}"

    # Get GitHub token from integration manager
    try:
        github_token = await get_github_token(config.github_integration_id) or ""
    except Exception as e:
        logger.exception(
            f"Failed to get GitHub token for integration {config.github_integration_id}",
            extra={"github_integration_id": config.github_integration_id, "error": str(e)},
        )
        raise

    # Create sandbox with environment variables
    sandbox_name = config.sandbox_name or f"agent-{org}-{repo}"
    sandbox_config = SandboxEnvironmentConfig(
        name=sandbox_name,
        template=SandboxEnvironmentTemplate.DEFAULT_BASE,
        environment_variables={
            "POSTHOG_API_URL": config.posthog_api_url,
            "POSTHOG_PERSONAL_API_KEY": config.posthog_api_key or "",
            "GITHUB_TOKEN": github_token,
        },
        ttl_seconds=3600,  # 1 hour max
    )

    sandbox = None
    try:
        # 1. Create and start sandbox
        logger.info(
            f"Creating sandbox for {config.repository}",
            extra={"repository": config.repository, "sandbox_name": sandbox_name},
        )
        sandbox = await SandboxEnvironment.create(sandbox_config)
        logger.info(f"Sandbox {sandbox.id} created and running")

        # 2. Clone repository
        logger.info(
            f"Cloning {config.repository}",
            extra={"repository": config.repository, "sandbox_id": sandbox.id},
        )

        repo_url = f"https://x-access-token:{github_token}@github.com/{org}/{repo}.git"

        clone_cmd = (
            f"mkdir -p /tmp/workspace/repos/{org} && "
            f"cd /tmp/workspace/repos/{org} && "
            f"git clone {repo_url} {repo}"
        )

        clone_result = await sandbox.execute(clone_cmd, timeout_seconds=5 * 60)
        if clone_result.exit_code != 0:
            logger.exception(
                f"Failed to clone repository: {clone_result.stderr}",
                extra={
                    "repository": config.repository,
                    "sandbox_id": sandbox.id,
                    "exit_code": clone_result.exit_code,
                    "stderr": clone_result.stderr[:500],
                },
            )
            return clone_result

        # 3. Run agent with custom prompt
        logger.info(
            f"Running agent with prompt in {repo_path}",
            extra={
                "repository": config.repository,
                "sandbox_id": sandbox.id,
                "prompt": config.prompt[:100],  # Truncate for logging
            },
        )

        # Escape prompt for safe shell execution
        escaped_prompt = shlex.quote(config.prompt)

        agent_cmd = (
            f"cd {repo_path} && "
            f"git reset --hard HEAD && "
            f"IS_SANDBOX=True node /scripts/runAgent.mjs "
            f"--repositoryPath {repo_path} "
            f"--prompt {escaped_prompt} "
            f"--max-turns {config.max_turns}"
        )

        result = await sandbox.execute(agent_cmd, timeout_seconds=config.timeout_seconds)

        if result.exit_code == 0:
            logger.info(
                f"Agent execution completed successfully in sandbox {sandbox.id}",
                extra={"repository": config.repository, "sandbox_id": sandbox.id},
            )
        else:
            logger.exception(
                f"Agent execution failed in sandbox {sandbox.id}",
                extra={
                    "repository": config.repository,
                    "sandbox_id": sandbox.id,
                    "exit_code": result.exit_code,
                    "stderr": result.stderr[:500],  # Truncate for logging
                },
            )

        return result

    except Exception as e:
        logger.exception(
            f"Failed to execute agent in sandbox: {e}",
            extra={
                "repository": config.repository,
                "sandbox_id": sandbox.id if sandbox else None,
                "error": str(e),
            },
        )
        raise

    finally:
        # 4. Always cleanup sandbox
        if sandbox:
            try:
                logger.info(
                    f"Cleaning up sandbox {sandbox.id}",
                    extra={"sandbox_id": sandbox.id},
                )
                await sandbox.destroy()
            except Exception as e:
                logger.exception(
                    f"Failed to cleanup sandbox {sandbox.id}: {e}",
                    extra={"sandbox_id": sandbox.id, "error": str(e)},
                )


class AgentSandbox:
    """
    Context manager for running multiple agent commands in the same sandbox.

    This is useful when you need to run several agent tasks sequentially without
    the overhead of creating a new sandbox each time. The sandbox is automatically
    cleaned up when exiting the context.

    Usage:
        ```python
        from products.tasks.backend.services.run_agent_in_sandbox import AgentSandbox

        async with AgentSandbox(
            repository="posthog/posthog",
            github_integration_id=integration.id,
            posthog_api_key=user.personal_api_key,
        ) as sandbox:
            # Run multiple agent tasks in the same sandbox
            result1 = await sandbox.run_agent("Add docstrings to all public functions")
            result2 = await sandbox.run_agent("Fix all linting errors")
            result3 = await sandbox.run_agent("Add unit tests for new functions")

            return result1, result2, result3
        # Sandbox is automatically cleaned up here
        ```

    Args:
        repository: Repository in format "organization/repository"
        github_integration_id: ID of the GitHub integration for authentication
        posthog_api_url: PostHog API URL for telemetry (default: "https://app.posthog.com")
        posthog_api_key: PostHog API key for telemetry (optional)
        sandbox_name: Custom name for the sandbox (optional)
    """

    def __init__(
        self,
        repository: str,
        github_integration_id: int,
        posthog_api_url: str = "https://app.posthog.com",
        posthog_api_key: Optional[str] = None,
        sandbox_name: Optional[str] = None,
    ):
        self.repository = repository
        self.github_integration_id = github_integration_id
        self.posthog_api_url = posthog_api_url
        self.posthog_api_key = posthog_api_key
        self.sandbox_name = sandbox_name
        self.sandbox: Optional[SandboxEnvironment] = None
        self.repo_path: Optional[str] = None

    async def __aenter__(self):
        """Set up the sandbox and clone the repository."""
        org, repo = self.repository.lower().split("/")
        self.repo_path = f"/tmp/workspace/repos/{org}/{repo}"

        # Get GitHub token from integration manager
        github_token = await get_github_token(self.github_integration_id) or ""

        # Create sandbox
        sandbox_name = self.sandbox_name or f"agent-{org}-{repo}"
        sandbox_config = SandboxEnvironmentConfig(
            name=sandbox_name,
            template=SandboxEnvironmentTemplate.DEFAULT_BASE,
            environment_variables={
                "POSTHOG_API_URL": self.posthog_api_url,
                "POSTHOG_PERSONAL_API_KEY": self.posthog_api_key or "",
                "GITHUB_TOKEN": github_token,
            },
        )

        self.sandbox = await SandboxEnvironment.create(sandbox_config)
        logger.info(f"Sandbox {self.sandbox.id} created for repository {self.repository}")

        # Clone repository
        repo_url = f"https://x-access-token:{github_token}@github.com/{org}/{repo}.git"

        clone_cmd = (
            f"mkdir -p /tmp/workspace/repos/{org} && "
            f"cd /tmp/workspace/repos/{org} && "
            f"git clone {repo_url} {repo}"
        )

        await self.sandbox.execute(clone_cmd, timeout_seconds=5 * 60)
        logger.info(f"Repository {self.repository} cloned to {self.repo_path}")

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Clean up the sandbox."""
        if self.sandbox:
            try:
                await self.sandbox.destroy()
                logger.info(f"Sandbox {self.sandbox.id} cleaned up")
            except Exception as e:
                logger.exception(f"Failed to cleanup sandbox {self.sandbox.id}: {e}")

    async def run_agent(
        self,
        prompt: str,
        max_turns: int = 20,
        timeout_seconds: int = 20 * 60,
    ) -> ExecutionResult:
        """
        Run the agent with a custom prompt in the sandbox.

        Args:
            prompt: The instruction/task for the agent to execute
            max_turns: Maximum number of conversation turns (default: 20)
            timeout_seconds: Maximum execution time in seconds (default: 20 minutes)

        Returns:
            ExecutionResult: Contains stdout, stderr, exit_code, and optional error message

        Raises:
            RuntimeError: If sandbox is not initialized
        """
        if not self.sandbox or not self.repo_path:
            raise RuntimeError("Sandbox not initialized. Use 'async with AgentSandbox(...) as sandbox:'")

        # Escape prompt for safe shell execution
        escaped_prompt = shlex.quote(prompt)

        agent_cmd = (
            f"cd {self.repo_path} && "
            f"git reset --hard HEAD && "
            f"IS_SANDBOX=True node /scripts/runAgent.mjs "
            f"--repositoryPath {self.repo_path} "
            f"--prompt {escaped_prompt} "
            f"--max-turns {max_turns}"
        )

        logger.info(
            f"Running agent in sandbox {self.sandbox.id}",
            extra={"prompt": prompt[:100], "max_turns": max_turns},
        )

        result = await self.sandbox.execute(agent_cmd, timeout_seconds=timeout_seconds)

        if result.exit_code == 0:
            logger.info(f"Agent execution completed successfully in sandbox {self.sandbox.id}")
        else:
            logger.exception(
                f"Agent execution failed in sandbox {self.sandbox.id}",
                extra={"exit_code": result.exit_code, "stderr": result.stderr[:500]},
            )

        return result
