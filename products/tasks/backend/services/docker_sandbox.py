import os
import uuid
import logging
import subprocess
from typing import Optional

from django.conf import settings

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

from .sandbox import ExecutionResult, SandboxConfig, SandboxStatus

logger = logging.getLogger(__name__)

WORKING_DIR = "/tmp/workspace"
DEFAULT_TASK_TIMEOUT_SECONDS = 20 * 60  # 20 minutes
DEFAULT_IMAGE_NAME = "posthog-sandbox-base"


class DockerSandbox:
    """
    Docker-based sandbox for local development and testing.
    Implements the same interface as the Modal-based Sandbox.
    """

    id: str
    config: SandboxConfig
    _container_id: str
    _registry: dict[str, "DockerSandbox"] = {}

    def __init__(self, container_id: str, config: SandboxConfig):
        self._container_id = container_id
        self.id = container_id[:12]
        self.config = config
        DockerSandbox._registry[self.id] = self

    @staticmethod
    def _run(args: list[str], check: bool = False, timeout: int | None = None) -> subprocess.CompletedProcess:
        """Run a subprocess command with logging."""
        logger.debug(f"Running: {' '.join(args)}")
        result = subprocess.run(args, capture_output=True, text=True, check=check, timeout=timeout)
        if result.stdout:
            logger.debug(f"stdout: {result.stdout[:500]}")
        if result.stderr:
            logger.debug(f"stderr: {result.stderr[:500]}")
        if result.returncode != 0:
            logger.debug(f"exit code: {result.returncode}")
        return result

    @staticmethod
    def _ensure_image_exists() -> str:
        """Build the sandbox image if it doesn't exist."""
        result = DockerSandbox._run(["docker", "images", "-q", DEFAULT_IMAGE_NAME])

        if result.stdout.strip():
            return DEFAULT_IMAGE_NAME

        logger.info(f"Building {DEFAULT_IMAGE_NAME} image (this may take a few minutes)...")
        dockerfile_path = os.path.join(
            settings.BASE_DIR, "products/tasks/backend/sandbox/images/Dockerfile.sandbox-base"
        )

        DockerSandbox._run(
            [
                "docker",
                "build",
                "-f",
                dockerfile_path,
                "-t",
                DEFAULT_IMAGE_NAME,
                str(settings.BASE_DIR),
            ],
            check=True,
        )

        return DEFAULT_IMAGE_NAME

    @staticmethod
    def _get_image(config: SandboxConfig) -> str:
        """Get the image to use, checking for snapshots first."""
        if config.snapshot_id:
            try:
                snapshot = SandboxSnapshot.objects.get(id=config.snapshot_id)
                if snapshot.status == SandboxSnapshot.Status.COMPLETE:
                    snapshot_image = f"posthog-sandbox-snapshot:{snapshot.external_id}"
                    result = DockerSandbox._run(["docker", "images", "-q", snapshot_image])
                    if result.stdout.strip():
                        return snapshot_image
                    logger.warning(f"Snapshot image {snapshot_image} not found locally, using base image")
            except SandboxSnapshot.DoesNotExist:
                logger.warning(f"Snapshot {config.snapshot_id} not found, using base image")
            except Exception as e:
                logger.warning(f"Failed to load snapshot {config.snapshot_id}: {e}")

        return DockerSandbox._ensure_image_exists()

    @staticmethod
    def _transform_url_for_docker(url: str) -> str:
        """Transform localhost URLs to be accessible from inside Docker container."""
        return url.replace("localhost", "host.docker.internal").replace("127.0.0.1", "host.docker.internal")

    @staticmethod
    def create(config: SandboxConfig) -> "DockerSandbox":
        try:
            image = DockerSandbox._get_image(config)
            container_name = f"{config.name}-{uuid.uuid4().hex[:6]}"

            env_args = []
            if config.environment_variables:
                for key, value in config.environment_variables.items():
                    if value is not None:
                        if key == "POSTHOG_API_URL":
                            value = DockerSandbox._transform_url_for_docker(value)
                        env_args.extend(["-e", f"{key}={value}"])

            volume_args = []
            runagent_path = os.path.join(settings.BASE_DIR, "products/tasks/scripts/runAgent.mjs")
            if os.path.exists(runagent_path):
                volume_args.extend(["-v", f"{runagent_path}:/scripts/runAgent.mjs:ro"])

            docker_args = [
                "docker",
                "run",
                "-d",
                "--name",
                container_name,
                "--add-host",
                "host.docker.internal:host-gateway",
                "-w",
                WORKING_DIR,
                f"--memory={config.memory_gb}g",
                f"--cpus={config.cpu_cores}",
                *env_args,
                *volume_args,
                image,
                "tail",
                "-f",
                "/dev/null",  # Keep container running
            ]

            result = DockerSandbox._run(docker_args, check=True)
            container_id = result.stdout.strip()

            sandbox = DockerSandbox(container_id=container_id, config=config)
            logger.info(f"Created Docker sandbox {sandbox.id} for {config.name}")

            return sandbox

        except subprocess.CalledProcessError as e:
            logger.exception(f"Failed to create Docker sandbox: {e.stderr}")
            raise SandboxProvisionError(
                "Failed to create Docker sandbox",
                {"config_name": config.name, "error": e.stderr},
                cause=e,
            )
        except Exception as e:
            logger.exception(f"Failed to create Docker sandbox: {e}")
            raise SandboxProvisionError(
                "Failed to create Docker sandbox",
                {"config_name": config.name, "error": str(e)},
                cause=e,
            )

    @staticmethod
    def get_by_id(sandbox_id: str) -> "DockerSandbox":
        if sandbox_id in DockerSandbox._registry:
            return DockerSandbox._registry[sandbox_id]

        try:
            result = DockerSandbox._run(
                ["docker", "inspect", "--format", "{{.Id}}", sandbox_id],
                check=True,
            )
            full_id = result.stdout.strip()
            config = SandboxConfig(name=f"sandbox-{sandbox_id}")
            return DockerSandbox(container_id=full_id, config=config)

        except subprocess.CalledProcessError as e:
            raise SandboxNotFoundError(
                f"Docker sandbox {sandbox_id} not found",
                {"sandbox_id": sandbox_id, "error": e.stderr},
                cause=e,
            )

    def get_status(self) -> SandboxStatus:
        try:
            result = DockerSandbox._run(
                ["docker", "inspect", "--format", "{{.State.Running}}", self._container_id],
                check=True,
            )
            is_running = result.stdout.strip().lower() == "true"
            return SandboxStatus.RUNNING if is_running else SandboxStatus.SHUTDOWN
        except subprocess.CalledProcessError:
            return SandboxStatus.SHUTDOWN

    def execute(
        self,
        command: str,
        timeout_seconds: Optional[int] = None,
    ) -> ExecutionResult:
        if not self.is_running():
            raise SandboxExecutionError(
                "Sandbox not in running state.",
                {"sandbox_id": self.id},
                cause=RuntimeError(f"Sandbox {self.id} is not running"),
            )

        if timeout_seconds is None:
            timeout_seconds = self.config.default_execution_timeout_seconds

        try:
            logger.debug(f"Executing in sandbox {self.id}: {command[:100]}...")
            result = DockerSandbox._run(
                ["docker", "exec", self._container_id, "bash", "-c", command],
                timeout=timeout_seconds,
            )

            return ExecutionResult(
                stdout=result.stdout,
                stderr=result.stderr,
                exit_code=result.returncode,
                error=None,
            )

        except subprocess.TimeoutExpired as e:
            raise SandboxTimeoutError(
                f"Execution timed out after {timeout_seconds} seconds",
                {"sandbox_id": self.id, "timeout_seconds": timeout_seconds},
                cause=e,
            )
        except Exception as e:
            logger.exception(f"Failed to execute command: {e}")
            raise SandboxExecutionError(
                "Failed to execute command",
                {"sandbox_id": self.id, "command": command, "error": str(e)},
                cause=e,
            )

    def clone_repository(self, repository: str, github_token: Optional[str] = "") -> ExecutionResult:
        if not self.is_running():
            raise RuntimeError("Sandbox not in running state.")

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
        if not self.is_running():
            raise RuntimeError("Sandbox not in running state.")

        org, repo = repository.lower().split("/")
        repo_path = f"/tmp/workspace/repos/{org}/{repo}"

        check_result = self.execute(f"test -d {repo_path} && echo 'exists' || echo 'missing'")
        if "missing" in check_result.stdout:
            raise RuntimeError(f"Repository path {repo_path} does not exist. Clone the repository first.")

        agent_setup_command = self._get_setup_command(repo_path)
        setup_command = f"cd {repo_path} && {agent_setup_command}"

        result = self.execute(setup_command, timeout_seconds=15 * 60)

        return result

    def is_git_clean(self, repository: str) -> tuple[bool, str]:
        if not self.is_running():
            raise RuntimeError("Sandbox not in running state.")

        org, repo = repository.lower().split("/")
        repo_path = f"/tmp/workspace/repos/{org}/{repo}"

        result = self.execute(f"cd {repo_path} && git status --porcelain")
        is_clean = not result.stdout.strip()

        return is_clean, result.stdout

    def execute_task(self, task_id: str, run_id: str, repository: str) -> ExecutionResult:
        if not self.is_running():
            raise RuntimeError("Sandbox not in running state.")

        org, repo = repository.lower().split("/")
        repo_path = f"/tmp/workspace/repos/{org}/{repo}"

        task_command = self._get_task_command(task_id, run_id, repo_path)
        command = f"cd {repo_path} && {task_command}"

        logger.info(f"Executing task {task_id} for run {run_id} in {repo_path} in sandbox {self.id}")
        logger.info(f"Task command: {task_command}")
        logger.info(f"Full command: {command}")

        result = self.execute(command, timeout_seconds=DEFAULT_TASK_TIMEOUT_SECONDS)

        logger.info(f"Task execution completed: exit_code={result.exit_code}")
        logger.info(f"Task stdout length: {len(result.stdout)} chars")
        logger.info(f"Task stderr length: {len(result.stderr)} chars")
        if result.exit_code != 0:
            logger.warning(f"Task stdout preview: {result.stdout[:500]}")
            logger.warning(f"Task stderr preview: {result.stderr[:500]}")

        return result

    def _get_task_command(self, task_id: str, run_id: str, repo_path: str) -> str:
        return f"git reset --hard HEAD && IS_SANDBOX=True node /scripts/runAgent.mjs --taskId {task_id} --runId {run_id} --repositoryPath {repo_path}"

    def _get_setup_command(self, repo_path: str) -> str:
        return f"git reset --hard HEAD && IS_SANDBOX=True && node /scripts/runAgent.mjs --repositoryPath {repo_path} --prompt '{SETUP_REPOSITORY_PROMPT.format(cwd=repo_path, repository=repo_path)}' --max-turns 20"

    def create_snapshot(self) -> str:
        if not self.is_running():
            raise SandboxExecutionError(
                "Sandbox not in running state.",
                {"sandbox_id": self.id},
                cause=RuntimeError(f"Sandbox {self.id} is not running"),
            )

        try:
            snapshot_id = uuid.uuid4().hex[:12]
            tag = f"posthog-sandbox-snapshot:{snapshot_id}"

            DockerSandbox._run(["docker", "commit", self._container_id, tag], check=True)

            logger.info(f"Created snapshot for sandbox {self.id}, snapshot ID: {snapshot_id}")

            return snapshot_id

        except subprocess.CalledProcessError as e:
            logger.exception(f"Failed to create snapshot: {e.stderr}")
            raise SnapshotCreationError(
                f"Failed to create snapshot: {e.stderr}",
                {"sandbox_id": self.id, "error": e.stderr},
                cause=e,
            )
        except Exception as e:
            logger.exception(f"Failed to create snapshot: {e}")
            raise SnapshotCreationError(
                f"Failed to create snapshot: {e}",
                {"sandbox_id": self.id, "error": str(e)},
                cause=e,
            )

    @staticmethod
    def delete_snapshot(external_id: str) -> None:
        logger.info(f"Deleting snapshot {external_id}")
        try:
            DockerSandbox._run(["docker", "rmi", f"posthog-sandbox-snapshot:{external_id}"])
            logger.info(f"Snapshot {external_id} deleted")
        except Exception as e:
            logger.warning(f"Failed to delete snapshot {external_id}: {e}")

    def destroy(self) -> None:
        try:
            DockerSandbox._run(["docker", "stop", self._container_id], timeout=30)
            DockerSandbox._run(["docker", "rm", self._container_id])
            DockerSandbox._registry.pop(self.id, None)
            logger.info(f"Destroyed Docker sandbox {self.id}")
        except Exception as e:
            logger.exception(f"Failed to destroy Docker sandbox: {e}")
            raise SandboxCleanupError(
                f"Failed to destroy Docker sandbox: {e}",
                {"sandbox_id": self.id, "error": str(e)},
                cause=e,
            )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.destroy()

    def is_running(self) -> bool:
        return self.get_status() == SandboxStatus.RUNNING

    @property
    def name(self) -> str:
        return self.config.name
