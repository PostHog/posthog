import os
import logging
from enum import Enum
from typing import Optional

from asgiref.sync import sync_to_async
from pydantic import BaseModel
from runloop_api_client import (
    AsyncRunloop,
    NotFoundError as RunloopNotFoundError,
)

from products.tasks.backend.models import SandboxSnapshot

logger = logging.getLogger(__name__)


class NotFoundError(Exception):
    pass


class SandboxEnvironmentStatus(str, Enum):
    PROVISIONING = "provisioning"
    INITIALIZING = "initializing"
    RUNNING = "running"
    SUSPENDING = "suspending"
    SUSPENDED = "suspended"
    RESUMING = "resuming"
    FAILURE = "failure"
    SHUTDOWN = "shutdown"


class SandboxEnvironmentSnapshotStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    COMPLETE = "complete"
    ERROR = "error"


class SandboxEnvironmentTemplate(str, Enum):
    UBUNTU_LATEST_X86_64 = "ubuntu_latest_x86_64"
    DEFAULT_BASE = "default_base"


class ExecutionResult(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    error: Optional[str] = None


class SandboxEnvironmentConfig(BaseModel):
    name: str
    template: SandboxEnvironmentTemplate = SandboxEnvironmentTemplate.DEFAULT_BASE
    default_execution_timeout_seconds: int = 10 * 60  # 10 minutes
    environment_variables: Optional[dict[str, str]] = None
    entrypoint: Optional[str] = None
    snapshot_id: Optional[str] = None
    ttl_seconds: int = 60 * 30  # 30 minutes


def get_runloop_client() -> AsyncRunloop:
    api_key = os.environ.get("RUNLOOP_API_KEY")
    if not api_key:
        raise ValueError("RUNLOOP_API_KEY environment variable is required")
    return AsyncRunloop(bearer_token=api_key)


TEMPLATE_TO_BLUEPRINT_NAME = {
    SandboxEnvironmentTemplate.DEFAULT_BASE: "sandbox-base-1",
}

BLUEPRINT_NAME_TO_TEMPLATE = {v: k for k, v in TEMPLATE_TO_BLUEPRINT_NAME.items()}


class SandboxEnvironment:
    """
    Abstraction layer for sandbox environments.
    Currently uses Runloop as the backend provider.
    """

    id: str
    status: SandboxEnvironmentStatus
    config: SandboxEnvironmentConfig
    _client: AsyncRunloop

    def __init__(self, id: str, status: SandboxEnvironmentStatus, config: SandboxEnvironmentConfig):
        self.id = id
        self.status = status
        self.config = config
        self._client = get_runloop_client()

    @staticmethod
    async def create(config: SandboxEnvironmentConfig) -> "SandboxEnvironment":
        client = get_runloop_client()

        blueprint_name = TEMPLATE_TO_BLUEPRINT_NAME.get(config.template)

        if not blueprint_name:
            raise RuntimeError(f"Unknown template for sandbox {config.name}")

        snapshot_external_id = None

        if config.snapshot_id:
            snapshot = await sync_to_async(SandboxSnapshot.objects.get)(id=config.snapshot_id)

            if snapshot.status == SandboxSnapshot.Status.COMPLETE:
                snapshot_external_id = snapshot.external_id

        try:
            # Wait for devbox to be running before returning
            devbox = await client.devboxes.create_and_await_running(
                name=config.name,
                environment_variables=config.environment_variables or {},
                entrypoint=config.entrypoint,
                launch_parameters={
                    "keep_alive_time_seconds": config.ttl_seconds,
                },
                **(
                    {"snapshot_id": snapshot_external_id}
                    if snapshot_external_id
                    else {"blueprint_name": blueprint_name}
                ),
            )

        except Exception as e:
            logger.exception(f"Failed to create sandbox: {e}")
            raise RuntimeError(f"Failed to create sandbox: {e}")

        sandbox = SandboxEnvironment(id=devbox.id, status=SandboxEnvironmentStatus(devbox.status), config=config)

        assert sandbox.is_running

        logger.info(f"Created sandbox {sandbox.id} with status: {devbox.status}")

        return sandbox

    @staticmethod
    async def get_by_id(sandbox_id: str) -> "SandboxEnvironment":
        client = get_runloop_client()

        try:
            devbox = await client.devboxes.retrieve(sandbox_id)

            if not devbox.blueprint_id:
                raise RuntimeError(f"Unknown template for sandbox {sandbox_id}")

            blueprint = await client.blueprints.retrieve(devbox.blueprint_id)

            template = BLUEPRINT_NAME_TO_TEMPLATE[blueprint.name]

            if not template:
                raise RuntimeError(f"Unknown template for sandbox {sandbox_id}")

            config = SandboxEnvironmentConfig(name=devbox.name or f"sandbox-{sandbox_id}", template=template)

            sandbox = SandboxEnvironment(id=devbox.id, status=SandboxEnvironmentStatus(devbox.status), config=config)

            logger.info(f"Retrieved sandbox {sandbox_id} with status: {sandbox.status}")

            return sandbox

        except Exception as e:
            if isinstance(e, RunloopNotFoundError):
                raise NotFoundError(f"Sandbox {sandbox_id} not found")
            logger.exception(f"Failed to retrieve sandbox {sandbox_id}: {e}")
            raise RuntimeError(f"Failed to retrieve sandbox {sandbox_id}: {e}")

    async def execute(
        self,
        command: str,
        timeout_seconds: Optional[int] = None,
    ) -> ExecutionResult:
        if not self.is_running:
            raise RuntimeError(f"Sandbox not in running state. Current status: {self.status}")

        if timeout_seconds is None:
            timeout_seconds = self.config.default_execution_timeout_seconds

        execution = await self._client.devboxes.executions.execute_async(
            self.id,
            command=command,
            timeout=timeout_seconds,
        )

        # Wait for execution to complete
        final_execution = await self._client.devboxes.wait_for_command(
            execution_id=execution.execution_id,
            devbox_id=self.id,
            statuses=["completed"],
            timeout_seconds=timeout_seconds,
        )

        result = ExecutionResult(
            stdout=final_execution.stdout,
            stderr=final_execution.stderr,
            exit_code=final_execution.exit_status,
            error=getattr(final_execution, "error", None),
        )

        if result.error:
            logger.warning(f"Command execution had error: {result.error}")

        return result

    async def initiate_snapshot(self) -> str:
        if not self.is_running:
            raise RuntimeError(f"Sandbox not in running state. Current status: {self.status}")

        try:
            devbox = await self._client.devboxes.retrieve(self.id)

            snapshot = await self._client.devboxes.snapshot_disk_async(devbox.id)

            snapshot_id = snapshot.id

            logger.info(f"Initiated snapshot for sandbox {self.id}, snapshot ID: {snapshot_id}")

            return snapshot_id

        except Exception as e:
            logger.exception(f"Failed to initiate snapshot: {e}")
            raise RuntimeError(f"Failed to initiate snapshot: {e}")

    @staticmethod
    async def get_snapshot_status(external_id: str) -> SandboxEnvironmentSnapshotStatus:
        try:
            client = get_runloop_client()

            logger.info(f"Getting snapshot status for {external_id}")

            snapshot = await client.devboxes.disk_snapshots.query_status(external_id)

            logger.info(f"Retrieved snapshot status for {external_id}: {snapshot.status}")

            return SandboxEnvironmentSnapshotStatus(snapshot.status)
        except Exception as e:
            logger.exception(f"Failed to get snapshot status: {e}")
            raise RuntimeError(f"Failed to get snapshot status: {e}")

    async def destroy(self) -> None:
        try:
            await self._client.devboxes.shutdown(self.id)

            self.status = SandboxEnvironmentStatus.SHUTDOWN

            logger.info(f"Destroyed sandbox {self.id}")

        except Exception as e:
            logger.exception(f"Failed to destroy sandbox: {e}")
            raise RuntimeError(f"Failed to destroy sandbox: {e}")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.destroy()

    @property
    def is_running(self) -> bool:
        return self.status == SandboxEnvironmentStatus.RUNNING

    @property
    def name(self) -> str:
        return self.config.name
