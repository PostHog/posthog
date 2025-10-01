import logging

from pydantic import BaseModel

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

    async def setup_repository(self) -> ExecutionResult:
        if not self.sandbox.is_running:
            raise RuntimeError(f"Sandbox not in running state. Current status: {self.sandbox.status}")

        return await self.clone_repository(self.config.repository_url)

    async def clone_repository(self, repo_url: str) -> ExecutionResult:
        if not self.sandbox.is_running:
            raise RuntimeError(f"Sandbox not in running state. Current status: {self.sandbox.status}")

        if repo_url.startswith("https://github.com/"):
            auth_url = repo_url.replace(
                "https://github.com/",
                f"https://x-access-token:{self.config.github_token}@github.com/",
            )
        else:
            raise ValueError("Only GitHub is supported")

        clone_command = f"git clone {auth_url} {WORKING_DIR}/{REPOSITORY_TARGET_DIR}"

        logger.info(f"Cloning repository {repo_url} to {self.repository_dir} in sandbox {self.sandbox.id}")
        return await self.sandbox.execute(clone_command)

    async def execute_task(self) -> ExecutionResult:
        """Execute Claude Code commands in the sandbox."""
        if not self.sandbox.is_running:
            raise RuntimeError(f"Sandbox not in running state. Current status: {self.sandbox.status}")

        full_command = f"cd {self.repository_dir} && {self.get_task_command()}"

        logger.info(
            f"Executing task {self.config.task_id} in directory {self.repository_dir} in sandbox {self.sandbox.id}"
        )
        return await self.sandbox.execute(full_command, timeout_seconds=DEFAULT_TASK_TIMEOUT_SECONDS)

    def get_task_command(self) -> str:
        """Get the command to execute the task."""
        # TODO: Replace with actual task execution: posthog-cli task run --task-id {self.config.task_id}
        return "posthog-cli --help"

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
