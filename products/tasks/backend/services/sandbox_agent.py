import logging

from pydantic import BaseModel

from products.tasks.backend.lib.constants import SETUP_REPOSITORY_PROMPT

from .sandbox_environment import ExecutionResult, SandboxEnvironment, SandboxEnvironmentConfig

logger = logging.getLogger(__name__)

WORKING_DIR = "/tmp/workspace"
REPOSITORY_TARGET_DIR = "repo"
DEFAULT_TASK_TIMEOUT_SECONDS = 20 * 60  # 20 minutes


class SandboxAgentConfig(BaseModel):
    repository_url: str
    github_token: str
    task_id: str
    posthog_personal_api_key: str
    posthog_project_id: str


class SandboxAgent:
    """
    Agent that uses sandbox environments to execute tasks.
    """

    config: SandboxAgentConfig
    sandbox: SandboxEnvironment

    def __init__(self, sandbox: SandboxEnvironment, config: SandboxAgentConfig):
        self.sandbox = sandbox
        self.config = config

    @classmethod
    async def create(
        cls,
        sandbox: SandboxEnvironment,
        config: SandboxAgentConfig,
    ) -> "SandboxAgent":
        environment_variables = {
            "REPOSITORY_URL": config.repository_url,
            "POSTHOG_CLI_TOKEN": config.posthog_personal_api_key,
            "POSTHOG_CLI_ENV_ID": config.posthog_project_id,
        }

        sandbox_config = SandboxEnvironmentConfig(
            name=sandbox.config.name,
            template=sandbox.config.template,
            environment_variables=environment_variables,
            entrypoint=sandbox.config.entrypoint,
        )

        sandbox = await SandboxEnvironment.create(sandbox_config)
        agent = cls(sandbox, config)

        return agent

    async def clone_repository(self, repository: str, github_token: str) -> ExecutionResult:
        """Clone a repository into the expected location.

        Args:
            repository: Repository in format "org/repo"
            github_token: GitHub access token

        Returns:
            ExecutionResult from the clone command
        """
        if not self.sandbox.is_running:
            raise RuntimeError(f"Sandbox not in running state. Current status: {self.sandbox.status}")

        org, repo = repository.split("/")
        repo_url = f"https://x-access-token:{github_token}@github.com/{repository}.git"
        target_path = f"/tmp/workspace/repos/{org}/{repo}"

        # Wipe existing directory if present, then clone
        clone_command = (
            f"rm -rf {target_path} && "
            f"mkdir -p /tmp/workspace/repos/{org} && "
            f"cd /tmp/workspace/repos/{org} && "
            f"git clone {repo_url} {repo}"
        )

        logger.info(f"Cloning repository {repository} to {target_path} in sandbox {self.sandbox.id}")
        return await self.sandbox.execute(clone_command, timeout_seconds=5 * 60)

    async def setup_repository(self, repository: str) -> ExecutionResult:
        if not self.sandbox.is_running:
            raise RuntimeError(f"Sandbox not in running state. Current status: {self.sandbox.status}")

        org, repo = repository.split("/")
        repo_path = f"/tmp/workspace/repos/{org}/{repo}"

        check_result = await self.sandbox.execute(f"test -d {repo_path} && echo 'exists' || echo 'missing'")
        if "missing" in check_result.stdout:
            raise RuntimeError(f"Repository path {repo_path} does not exist. Clone the repository first.")

        setup_command = f"cd {repo_path} && {self.get_setup_command()}"

        logger.info(f"Running code agent setup for {repository} in sandbox {self.sandbox.id}")
        return await self.sandbox.execute(setup_command, timeout_seconds=15 * 60)

    async def execute_task(self) -> ExecutionResult:
        """Execute PostHog Code Agent commands in the sandbox."""
        if not self.sandbox.is_running:
            raise RuntimeError(f"Sandbox not in running state. Current status: {self.sandbox.status}")

        full_command = f"cd {self.repository_dir} && {self.get_task_command()}"

        logger.info(
            f"Executing task {self.config.task_id} in directory {self.repository_dir} in sandbox {self.sandbox.id}"
        )
        return await self.sandbox.execute(full_command, timeout_seconds=DEFAULT_TASK_TIMEOUT_SECONDS)

    def get_task_command(self) -> str:
        """Get the command to execute the task."""
        return f"npx @posthog/code-agent --task-id {self.config.task_id}"

    def get_setup_command(self) -> str:
        """Get the command to setup the repository."""
        return f"npx @posthog/code-agent --prompt {SETUP_REPOSITORY_PROMPT.format(cwd=self.working_dir, repository=self.repository_dir)}"

    async def destroy(self) -> None:
        """Destroy the underlying sandbox."""
        await self.sandbox.destroy()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.destroy()

    @property
    def working_dir(self) -> str:
        return WORKING_DIR

    @property
    def repository_dir(self) -> str:
        return f"{WORKING_DIR}/{REPOSITORY_TARGET_DIR}"

    @property
    def is_running(self) -> bool:
        return self.sandbox.is_running

    @property
    def id(self) -> str:
        return self.sandbox.id

    @property
    def status(self):
        return self.sandbox.status
