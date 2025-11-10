import logging
from enum import Enum
from typing import Optional

import modal
from pydantic import BaseModel

from products.tasks.backend.constants import SETUP_REPOSITORY_PROMPT
from products.tasks.backend.models import SandboxSnapshot
from products.tasks.backend.temporal.exceptions import (
    SandboxCleanupError,
    SandboxExecutionError,
    SandboxNotFoundError,
    SandboxProvisionError,
    SandboxTimeoutError,
    SnapshotCreationError,
)

logger = logging.getLogger(__name__)

WORKING_DIR = "/tmp/workspace"
REPOSITORY_TARGET_DIR = "repo"
DEFAULT_TASK_TIMEOUT_SECONDS = 20 * 60  # 20 minutes
DEFAULT_MODAL_APP_NAME = "posthog-sandbox-default"


class SandboxStatus(str, Enum):
    RUNNING = "running"
    SHUTDOWN = "shutdown"


class SandboxTemplate(str, Enum):
    DEFAULT_BASE = "default_base"


class ExecutionResult(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    error: Optional[str] = None


class SandboxConfig(BaseModel):
    name: str
    template: SandboxTemplate = SandboxTemplate.DEFAULT_BASE
    default_execution_timeout_seconds: int = 10 * 60  # 10 minutes
    environment_variables: Optional[dict[str, str]] = None
    snapshot_id: Optional[str] = None
    ttl_seconds: int = 60 * 30  # 30 minutes
    metadata: Optional[dict[str, str]] = None
    memory_gb: int = 16
    cpu_cores: int = 4
    disk_size_gb: int = 64


TEMPLATE_TO_IMAGE = {
    SandboxTemplate.DEFAULT_BASE: modal.Image.from_registry("ghcr.io/posthog/posthog-sandbox-base:master"),
}


class Sandbox:
    """
    A box in the cloud. Sand optional.
    """

    id: str
    status: SandboxStatus
    config: SandboxConfig
    _sandbox: modal.Sandbox
    _app: modal.App

    def __init__(self, sandbox: modal.Sandbox, status: SandboxStatus, config: SandboxConfig):
        self.id = sandbox.object_id
        self.status = status
        self.config = config
        self._sandbox = sandbox
        self._app = Sandbox._get_default_app()

    @staticmethod
    def _get_default_app() -> modal.App:
        return modal.App.lookup(DEFAULT_MODAL_APP_NAME, create_if_missing=True)

    @staticmethod
    def create(config: SandboxConfig) -> "Sandbox":
        try:
            app = Sandbox._get_default_app()

            image = TEMPLATE_TO_IMAGE.get(config.template)

            if not image:
                raise SandboxProvisionError(
                    f"Unknown template for sandbox {config.name}", {"template": str(config.template), "config": config}
                )

            if config.snapshot_id:
                snapshot = SandboxSnapshot.objects.get(id=config.snapshot_id)
                if snapshot.status == SandboxSnapshot.Status.COMPLETE:
                    try:
                        image = modal.Image.from_id(snapshot.external_id)
                    except Exception as e:
                        logger.warning(f"Failed to load snapshot image {snapshot.external_id}: {e}")

            secrets = []
            if config.environment_variables:
                secret = modal.Secret.from_dict(config.environment_variables)
                secrets.append(secret)

            create_kwargs = {
                "app": app,
                "name": config.name,
                "image": image,
                "timeout": config.ttl_seconds,
                "cpu": float(config.cpu_cores),
                "memory": config.memory_gb * 1024,
            }

            if secrets:
                create_kwargs["secrets"] = secrets

            sb = modal.Sandbox.create(**create_kwargs)

            if config.metadata:
                sb.set_tags(config.metadata)

            sandbox = Sandbox(sandbox=sb, status=SandboxStatus.RUNNING, config=config)

            logger.info(f"Created sandbox {sandbox.id} for {config.name}")

            return sandbox

        except Exception as e:
            logger.exception(f"Failed to create sandbox: {e}")
            raise SandboxProvisionError(f"Failed to create sandbox", {"config": config, "error": str(e)})

    @staticmethod
    def get_by_id(sandbox_id: str) -> "Sandbox":
        try:
            sb = modal.Sandbox.from_id(sandbox_id)

            config = SandboxConfig(name=getattr(sb, "name", f"sandbox-{sandbox_id}"))

            # TRICKY: Modal does not expose the status of the sandbox, so we need to check if the sandbox is running by executing a command.
            status = SandboxStatus.RUNNING
            try:
                process = sb.exec("echo", "test")
                process.wait()
            except Exception:
                status = SandboxStatus.SHUTDOWN

            sandbox = Sandbox(sandbox=sb, status=status, config=config)

            logger.info(f"Retrieved sandbox {sandbox_id} with status {status}")

            return sandbox

        except Exception as e:
            logger.exception(f"Failed to retrieve sandbox {sandbox_id}: {e}")
            raise SandboxNotFoundError(f"Sandbox {sandbox_id} not found", {"sandbox_id": sandbox_id, "error": str(e)})

    def execute(
        self,
        command: str,
        timeout_seconds: Optional[int] = None,
    ) -> ExecutionResult:
        if not self.is_running:
            raise SandboxExecutionError(
                f"Sandbox not in running state. Current status: {self.status}",
                {"sandbox_id": self.id, "status": str(self.status)},
            )

        if timeout_seconds is None:
            timeout_seconds = self.config.default_execution_timeout_seconds

        try:
            process = self._sandbox.exec("bash", "-c", command, timeout=timeout_seconds)

            process.wait()

            stdout = process.stdout.read()
            stderr = process.stderr.read()

            result = ExecutionResult(
                stdout=stdout.decode("utf-8") if isinstance(stdout, bytes) else stdout,
                stderr=stderr.decode("utf-8") if isinstance(stderr, bytes) else stderr,
                exit_code=process.returncode,
                error=None,
            )

            return result

        except TimeoutError:
            raise SandboxTimeoutError(
                f"Execution timed out after {timeout_seconds} seconds",
                {"sandbox_id": self.id, "timeout_seconds": timeout_seconds},
            )
        except Exception as e:
            logger.exception(f"Failed to execute command: {e}")
            raise SandboxExecutionError(
                f"Failed to execute command",
                {"sandbox_id": self.id, "command": command, "error": str(e)},
            )

    def clone_repository(self, repository: str, github_token: Optional[str] = "") -> ExecutionResult:
        if not self.is_running:
            raise RuntimeError(f"Sandbox not in running state. Current status: {self.status}")

        org, repo = repository.lower().split("/")
        repo_url = (
            f"https://x-access-token:{github_token}@github.com/{org}/{repo}.git"
            if github_token
            else f"https://github.com/{org}/{repo}.git"
        )

        target_path = f"/tmp/workspace/repos/{org}/{repo}"

        clone_command = (
            f"rm -rf {target_path} && "
            f"mkdir -p /tmp/workspace/repos/{org} && "
            f"cd /tmp/workspace/repos/{org} && "
            f"git clone {repo_url} {repo}"
        )

        logger.info(f"Cloning repository {repository} to {target_path} in sandbox {self.id}")
        return self.execute(clone_command, timeout_seconds=5 * 60)

    def setup_repository(self, repository: str) -> ExecutionResult:
        if not self.is_running:
            raise RuntimeError(f"Sandbox not in running state. Current status: {self.status}")

        org, repo = repository.lower().split("/")
        repo_path = f"/tmp/workspace/repos/{org}/{repo}"

        check_result = self.execute(f"test -d {repo_path} && echo 'exists' || echo 'missing'")
        if "missing" in check_result.stdout:
            raise RuntimeError(f"Repository path {repo_path} does not exist. Clone the repository first.")

        setup_command = f"cd {repo_path} && {self._get_setup_command(repo_path)}"

        logger.info(f"Running code agent setup for {repository} in sandbox {self.id}")
        return self.execute(setup_command, timeout_seconds=15 * 60)

    def is_git_clean(self, repository: str) -> tuple[bool, str]:
        if not self.is_running:
            raise RuntimeError(f"Sandbox not in running state. Current status: {self.status}")

        org, repo = repository.lower().split("/")
        repo_path = f"/tmp/workspace/repos/{org}/{repo}"

        result = self.execute(f"cd {repo_path} && git status --porcelain")
        is_clean = not result.stdout.strip()

        return is_clean, result.stdout

    def execute_task(self, task_id: str, repository: str) -> ExecutionResult:
        if not self.is_running:
            raise RuntimeError(f"Sandbox not in running state. Current status: {self.status}")

        org, repo = repository.lower().split("/")
        repo_path = f"/tmp/workspace/repos/{org}/{repo}"

        command = f"cd {repo_path} && {self._get_task_command(task_id, repo_path)}"

        logger.info(f"Executing task {task_id} in {repo_path} in sandbox {self.id}")
        return self.execute(command, timeout_seconds=DEFAULT_TASK_TIMEOUT_SECONDS)

    def _get_task_command(self, task_id: str, repo_path: str) -> str:
        return f"git reset --hard HEAD && IS_SANDBOX=True node /scripts/runAgent.mjs --taskId {task_id} --repositoryPath {repo_path}"

    def _get_setup_command(self, repo_path: str) -> str:
        return f"git reset --hard HEAD && IS_SANDBOX=True && node /scripts/runAgent.mjs --repositoryPath {repo_path} --prompt '{SETUP_REPOSITORY_PROMPT.format(cwd=repo_path, repository=repo_path)}' --max-turns 20"

    def create_snapshot(self) -> str:
        if not self.is_running:
            raise SandboxExecutionError(
                f"Sandbox not in running state. Current status: {self.status}",
                {"sandbox_id": self.id, "status": str(self.status)},
            )

        try:
            image = self._sandbox.snapshot_filesystem()

            snapshot_id = image.object_id

            logger.info(f"Created snapshot for sandbox {self.id}, snapshot ID: {snapshot_id}")

            return snapshot_id

        except Exception as e:
            logger.exception(f"Failed to create snapshot: {e}")
            raise SnapshotCreationError(f"Failed to create snapshot: {e}", {"sandbox_id": self.id, "error": str(e)})

    @staticmethod
    def delete_snapshot(external_id: str) -> None:
        logger.info(f"Deleting snapshot {external_id}")
        try:
            logger.info(f"Snapshot {external_id} marked for cleanup")
        except Exception as e:
            logger.warning(f"Failed to delete snapshot {external_id}: {e}")

    def destroy(self) -> None:
        try:
            self._sandbox.terminate()
            self.status = SandboxStatus.SHUTDOWN
            logger.info(f"Destroyed sandbox {self.id}")
        except Exception as e:
            logger.exception(f"Failed to destroy sandbox: {e}")
            raise SandboxCleanupError(f"Failed to destroy sandbox: {e}", {"sandbox_id": self.id, "error": str(e)})

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.destroy()

    @property
    def is_running(self) -> bool:
        return self.status == SandboxStatus.RUNNING

    @property
    def name(self) -> str:
        return self.config.name
