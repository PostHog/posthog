import os
import math
import time
import asyncio
import logging
from enum import Enum
from typing import Optional

from asgiref.sync import sync_to_async
from pydantic import BaseModel
from runloop_api_client import (
    APITimeoutError as RunloopAPITimeoutError,
    AsyncRunloop,
    BadRequestError as RunloopBadRequestError,
    NotFoundError as RunloopNotFoundError,
)

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


class SandboxStatus(str, Enum):
    PROVISIONING = "provisioning"
    INITIALIZING = "initializing"
    RUNNING = "running"
    SUSPENDING = "suspending"
    SUSPENDED = "suspended"
    RESUMING = "resuming"
    FAILURE = "failure"
    SHUTDOWN = "shutdown"


class SandboxSnapshotStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    ERROR = "error"


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
    entrypoint: Optional[str] = None
    snapshot_id: Optional[str] = None
    ttl_seconds: int = 60 * 30  # 30 minutes
    metadata: Optional[dict[str, str]] = None
    memory_gb: int = 16
    cpu_cores: int = 8
    disk_size_gb: int = 64


def get_runloop_client() -> AsyncRunloop:
    api_key = os.environ.get("RUNLOOP_API_KEY")
    if not api_key:
        raise ValueError("RUNLOOP_API_KEY environment variable is required")
    return AsyncRunloop(bearer_token=api_key)


TEMPLATE_TO_BLUEPRINT_NAME = {
    SandboxTemplate.DEFAULT_BASE: "sandbox-base-1",
}

BLUEPRINT_NAME_TO_TEMPLATE = {v: k for k, v in TEMPLATE_TO_BLUEPRINT_NAME.items()}


class Sandbox:
    """
    A box in the cloud. Sand optional.
    """

    id: str
    status: SandboxStatus
    config: SandboxConfig
    _client: AsyncRunloop

    def __init__(self, id: str, status: SandboxStatus, config: SandboxConfig):
        self.id = id
        self.status = status
        self.config = config
        self._client = get_runloop_client()

    @staticmethod
    async def create(config: SandboxConfig) -> "Sandbox":
        client = get_runloop_client()

        blueprint_name = TEMPLATE_TO_BLUEPRINT_NAME.get(config.template)

        if not blueprint_name:
            raise SandboxProvisionError(
                f"Unknown template for sandbox {config.name}", {"template": str(config.template), "config": config}
            )

        snapshot_external_id = None

        if config.snapshot_id:
            snapshot = await sync_to_async(SandboxSnapshot.objects.get)(id=config.snapshot_id)

            if snapshot.status == SandboxSnapshot.Status.COMPLETE:
                snapshot_external_id = snapshot.external_id

        try:
            # Wait for devbox to be running before returning
            create_kwargs = {
                "name": config.name,
                "environment_variables": config.environment_variables or {},
                "entrypoint": config.entrypoint,
                "metadata": config.metadata or {},
                "launch_parameters": {
                    "keep_alive_time_seconds": config.ttl_seconds,
                    "resource_size_request": "CUSTOM_SIZE",
                    "custom_cpu_cores": config.cpu_cores,
                    "custom_gb_memory": config.memory_gb,
                    "custom_disk_size": config.disk_size_gb,
                },
            }
            if snapshot_external_id:
                create_kwargs["snapshot_id"] = snapshot_external_id
            else:
                create_kwargs["blueprint_name"] = blueprint_name

            devbox = await client.devboxes.create_and_await_running(**create_kwargs)  # type: ignore[arg-type]

        except Exception as e:
            logger.exception(f"Failed to create sandbox: {e}")
            raise SandboxProvisionError(f"Failed to create sandbox", {"config": config, "error": str(e)})

        sandbox = Sandbox(id=devbox.id, status=SandboxStatus(devbox.status), config=config)

        assert sandbox.is_running

        logger.info(f"Created sandbox {sandbox.id} with status: {devbox.status}")

        return sandbox

    @staticmethod
    async def get_by_id(sandbox_id: str) -> "Sandbox":
        client = get_runloop_client()

        try:
            devbox = await client.devboxes.retrieve(sandbox_id)

            template = SandboxTemplate.DEFAULT_BASE

            if devbox.blueprint_id:
                blueprint = await client.blueprints.retrieve(devbox.blueprint_id)
                template = BLUEPRINT_NAME_TO_TEMPLATE.get(blueprint.name, SandboxTemplate.DEFAULT_BASE)

            config = SandboxConfig(name=devbox.name or f"sandbox-{sandbox_id}", template=template)

            sandbox = Sandbox(id=devbox.id, status=SandboxStatus(devbox.status), config=config)

            logger.info(f"Retrieved sandbox {sandbox_id} with status: {sandbox.status}")

            return sandbox

        except Exception as e:
            if isinstance(e, RunloopNotFoundError | RunloopBadRequestError):
                if "non-existent-sandbox-id" in str(e) or isinstance(e, RunloopNotFoundError):
                    raise SandboxNotFoundError(
                        f"Sandbox {sandbox_id} not found", {"sandbox_id": sandbox_id, "error": str(e)}
                    )
            raise SandboxProvisionError(
                f"Failed to retrieve sandbox {sandbox_id}", {"sandbox_id": sandbox_id, "error": str(e)}
            )

    async def execute(
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

        execution = await self._client.with_options(timeout=timeout_seconds).devboxes.executions.execute_async(
            self.id,
            command=command,
            timeout=timeout_seconds,
        )

        start_time = time.time()

        while True:
            elapsed_time = time.time() - start_time
            remaining_time = math.ceil(timeout_seconds - elapsed_time)

            if remaining_time <= 0:
                raise SandboxTimeoutError(
                    f"Execution timed out after {timeout_seconds} seconds",
                    {"sandbox_id": self.id, "timeout_seconds": timeout_seconds},
                )

            try:
                api_timeout = min(remaining_time, 60)  # Runloop only supports 60 second timeouts

                # TODO - unclear to me why we don't simply call wait_for_command with the
                # full timeout_seconds, and await it? Pre-planning for temporal?
                final_execution = await self._client.devboxes.wait_for_command(
                    execution_id=execution.execution_id,
                    devbox_id=self.id,
                    statuses=["completed"],
                    timeout_seconds=api_timeout,
                )

                break

            except RunloopAPITimeoutError:
                # TODO: Move this to a workflow.sleep() when used in a temporal workflow
                await asyncio.sleep(1)
                continue

        result = ExecutionResult(
            stdout=final_execution.stdout,
            stderr=final_execution.stderr,
            exit_code=final_execution.exit_status or 0,
            error=getattr(final_execution, "error", None),
        )

        return result

    async def clone_repository(self, repository: str, github_token: Optional[str] = "") -> ExecutionResult:
        if not self.is_running:
            raise RuntimeError(f"Sandbox not in running state. Current status: {self.status}")

        org, repo = repository.lower().split("/")
        repo_url = (
            f"https://x-access-token:{github_token}@github.com/{org}/{repo}.git"
            if github_token
            else f"https://github.com/{org}/{repo}.git"
        )

        target_path = f"/tmp/workspace/repos/{org}/{repo}"

        # Wipe existing directory if present, then clone
        clone_command = (
            f"rm -rf {target_path} && "
            f"mkdir -p /tmp/workspace/repos/{org} && "
            f"cd /tmp/workspace/repos/{org} && "
            f"git clone {repo_url} {repo}"
        )

        logger.info(f"Cloning repository {repository} to {target_path} in sandbox {self.id}")
        return await self.execute(clone_command, timeout_seconds=5 * 60)

    async def setup_repository(self, repository: str) -> ExecutionResult:
        """Setup a repository for snapshotting using the PostHog Code Agent."""
        if not self.is_running:
            raise RuntimeError(f"Sandbox not in running state. Current status: {self.status}")

        org, repo = repository.lower().split("/")
        repo_path = f"/tmp/workspace/repos/{org}/{repo}"

        check_result = await self.execute(f"test -d {repo_path} && echo 'exists' || echo 'missing'")
        if "missing" in check_result.stdout:
            raise RuntimeError(f"Repository path {repo_path} does not exist. Clone the repository first.")

        setup_command = f"cd {repo_path} && {self._get_setup_command(repo_path)}"

        logger.info(f"Running code agent setup for {repository} in sandbox {self.id}")
        return await self.execute(setup_command, timeout_seconds=15 * 60)

    async def is_git_clean(self, repository: str) -> tuple[bool, str]:
        if not self.is_running:
            raise RuntimeError(f"Sandbox not in running state. Current status: {self.status}")

        org, repo = repository.lower().split("/")
        repo_path = f"/tmp/workspace/repos/{org}/{repo}"

        result = await self.execute(f"cd {repo_path} && git status --porcelain")
        is_clean = not result.stdout.strip()

        return is_clean, result.stdout

    async def execute_task(self, task_id: str, repository: str) -> ExecutionResult:
        if not self.is_running:
            raise RuntimeError(f"Sandbox not in running state. Current status: {self.status}")

        org, repo = repository.lower().split("/")
        repo_path = f"/tmp/workspace/repos/{org}/{repo}"

        command = f"cd {repo_path} && {self._get_task_command(task_id, repo_path)}"

        logger.info(f"Executing task {task_id} in {repo_path} in sandbox {self.id}")
        return await self.execute(command, timeout_seconds=DEFAULT_TASK_TIMEOUT_SECONDS)

    def _get_task_command(self, task_id: str, repo_path: str) -> str:
        return f"git reset --hard HEAD && IS_SANDBOX=True node /scripts/runAgent.mjs --taskId {task_id} --repositoryPath {repo_path}"

    def _get_setup_command(self, repo_path: str) -> str:
        return f"git reset --hard HEAD && IS_SANDBOX=True && node /scripts/runAgent.mjs --repositoryPath {repo_path} --prompt '{SETUP_REPOSITORY_PROMPT.format(cwd=repo_path, repository=repo_path)}' --max-turns 20"

    async def initiate_snapshot(self, metadata: Optional[dict[str, str]] = None) -> str:
        if not self.is_running:
            raise SandboxExecutionError(
                f"Sandbox not in running state. Current status: {self.status}",
                {"sandbox_id": self.id, "status": str(self.status)},
            )

        try:
            devbox = await self._client.devboxes.retrieve(self.id)

            snapshot = await self._client.devboxes.snapshot_disk_async(devbox.id, metadata=metadata)

            snapshot_id = snapshot.id

            logger.info(f"Initiated snapshot for sandbox {self.id}, snapshot ID: {snapshot_id}")

            return snapshot_id

        except Exception as e:
            logger.exception(f"Failed to initiate snapshot: {e}")
            raise SnapshotCreationError(f"Failed to initiate snapshot: {e}", {"sandbox_id": self.id, "error": str(e)})

    @staticmethod
    async def delete_snapshot(external_id: str) -> None:
        client = get_runloop_client()
        logger.info(f"Deleting snapshot {external_id}")
        await client.devboxes.disk_snapshots.delete(external_id)
        logger.info(f"Deleted snapshot {external_id}")

    @staticmethod
    async def get_snapshot_status(external_id: str) -> SandboxSnapshotStatus:
        try:
            client = get_runloop_client()

            logger.info(f"Getting snapshot status for {external_id}")

            snapshot = await client.devboxes.disk_snapshots.query_status(external_id)

            logger.info(f"Retrieved snapshot status for {external_id}: {snapshot.status}")

            return SandboxSnapshotStatus(snapshot.status)
        except Exception as e:
            logger.exception(f"Failed to get snapshot status: {e}")
            raise SnapshotCreationError(
                f"Failed to get snapshot status: {e}", {"external_id": external_id, "error": str(e)}
            )

    async def destroy(self) -> None:
        try:
            await self._client.devboxes.shutdown(self.id)

            self.status = SandboxStatus.SHUTDOWN

            logger.info(f"Destroyed sandbox {self.id}")

        except Exception as e:
            logger.exception(f"Failed to destroy sandbox: {e}")
            raise SandboxCleanupError(f"Failed to destroy sandbox: {e}", {"sandbox_id": self.id, "error": str(e)})

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.destroy()

    @property
    def is_running(self) -> bool:
        return self.status == SandboxStatus.RUNNING

    @property
    def name(self) -> str:
        return self.config.name
