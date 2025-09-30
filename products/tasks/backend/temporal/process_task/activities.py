import asyncio
import logging

from asgiref.sync import sync_to_async
from temporalio import activity

from products.tasks.backend.models import SandboxSnapshot, Task
from products.tasks.backend.services.sandbox_agent import SandboxAgent
from products.tasks.backend.services.sandbox_environment import (
    NotFoundError,
    SandboxEnvironment,
    SandboxEnvironmentConfig,
    SandboxEnvironmentTemplate,
)

from .schemas import (
    CheckSnapshotExistsForRepositoryInput,
    CheckSnapshotExistsForRepositoryOutput,
    CleanupSandboxInput,
    CloneRepositoryInput,
    CreateSandboxFromSnapshotInput,
    CreateSnapshotInput,
    ExecuteTaskInput,
    GetSandboxForSetupInput,
    SetupRepositoryInput,
    TaskDetails,
)
from .utils import get_github_token

logger = logging.getLogger(__name__)


@activity.defn
async def get_task_details(task_id: str) -> TaskDetails:
    """Get task details from the database."""
    task = await sync_to_async(Task.objects.select_related("integration").get)(id=task_id)

    return TaskDetails(
        task_id=str(task.id),
        team_id=task.team_id,
        user_id=task.created_by_id,
        github_integration_id=task.integration_id,
        repository=task.integration.config.get("repository", ""),
    )


@activity.defn
async def check_snapshot_exists_for_repository(
    input: CheckSnapshotExistsForRepositoryInput,
) -> CheckSnapshotExistsForRepositoryOutput:
    """Check if a repository exists in the latest complete snapshot."""
    snapshot = await sync_to_async(SandboxSnapshot.get_latest_snapshot_with_repos)(
        input.github_integration_id, [input.repository], status=SandboxSnapshot.Status.COMPLETE
    )

    if snapshot:
        return CheckSnapshotExistsForRepositoryOutput(exists=True, snapshot_id=str(snapshot.id))

    return CheckSnapshotExistsForRepositoryOutput(exists=False, snapshot_id=None)


@activity.defn
async def get_sandbox_for_setup(input: GetSandboxForSetupInput) -> str:
    """
    Get sandbox for setup. Searches for existing snapshot to use as base,
    otherwise uses default template. Returns sandbox_id when sandbox is running.
    """
    # Try to find latest snapshot for this integration
    snapshot = await sync_to_async(SandboxSnapshot.get_latest_snapshot_for_integration)(input.github_integration_id)

    config = SandboxEnvironmentConfig(
        name=f"snapshot-setup-{activity.info().workflow_id[:8]}",
        template=SandboxEnvironmentTemplate.DEFAULT_BASE,
        environment_variables={},
        snapshot_id=snapshot.id if snapshot else None,
    )

    sandbox = await SandboxEnvironment.create(config)

    if not sandbox.is_running:
        raise RuntimeError("Sandbox not in running state")

    return sandbox.id


@activity.defn
async def clone_repository(input: CloneRepositoryInput) -> str:
    """Clone repository into sandbox."""

    github_token = await get_github_token(input.github_integration_id)

    sandbox = await SandboxEnvironment.get_by_id(input.sandbox_id)
    agent = SandboxAgent(sandbox)
    result = await agent.clone_repository(input.repository, github_token)

    if result.exit_code != 0:
        raise RuntimeError(f"Failed to clone repository: {result.stderr}")

    return result.stdout


@activity.defn
async def setup_repository(input: SetupRepositoryInput) -> str:
    """Setup a repository for snapshotting using the PostHog Code Agent."""
    sandbox = await SandboxEnvironment.get_by_id(input.sandbox_id)
    agent = SandboxAgent(sandbox)
    result = await agent.setup_repository(input.repository)

    if result.exit_code != 0:
        raise RuntimeError(f"Failed to setup repository: {result.stderr}")

    return result.stdout


@activity.defn
async def create_snapshot(input: CreateSnapshotInput) -> str:
    """Create and finalize snapshot."""
    sandbox = await SandboxEnvironment.get_by_id(input.sandbox_id)

    snapshot_external_id = await sandbox.initiate_snapshot()

    await sync_to_async(SandboxSnapshot.objects.create)(
        integration_id=input.github_integration_id,
        external_id=snapshot_external_id,
        status=SandboxSnapshot.Status.IN_PROGRESS,
    )

    # Poll until complete (max 20 minutes)
    max_polls = 80
    for _ in range(max_polls):
        status = await SandboxEnvironment.get_snapshot_status(snapshot_external_id)

        if status.value == "complete":
            await sync_to_async(SandboxSnapshot.objects.filter(external_id=snapshot_external_id).update)(
                status=SandboxSnapshot.Status.COMPLETE,
            )
            break
        elif status.value == "error":
            await sync_to_async(SandboxSnapshot.objects.filter(external_id=snapshot_external_id).update)(
                status=SandboxSnapshot.Status.ERROR,
            )
            raise RuntimeError("Snapshot creation failed")

        await asyncio.sleep(15)
    else:
        raise RuntimeError("Snapshot creation timed out")

    # Get base snapshot to determine repos list
    base_snapshot = await sync_to_async(SandboxSnapshot.get_latest_snapshot_for_integration)(
        input.github_integration_id
    )
    base_repos = base_snapshot.repos if base_snapshot else []
    new_repos = [*base_repos, input.repository]

    # Create snapshot record
    snapshot = await sync_to_async(SandboxSnapshot.objects.create)(
        integration_id=input.github_integration_id,
        repos=new_repos,
        external_id=snapshot_external_id,
        status=SandboxSnapshot.Status.COMPLETE,
    )

    return str(snapshot.id)


@activity.defn
async def create_sandbox_from_snapshot(input: CreateSandboxFromSnapshotInput) -> str:
    """Create a sandbox from a snapshot for task execution."""
    await sync_to_async(SandboxSnapshot.objects.get)(id=input.snapshot_id)

    config = SandboxEnvironmentConfig(
        name=f"task-execution-{activity.info().workflow_id[:8]}",
        environment_variables={},
        snapshot_id=input.snapshot_id,
    )

    sandbox = await SandboxEnvironment.create(config)

    return sandbox.id


@activity.defn
async def execute_task_in_sandbox(input: ExecuteTaskInput) -> None:
    """Execute the code agent task in the sandbox."""
    sandbox = await SandboxEnvironment.get_by_id(input.sandbox_id)
    agent = SandboxAgent(sandbox)

    result = await agent.execute_task(input.task_id, input.repository)

    if result.exit_code != 0:
        raise RuntimeError(f"Task execution failed: {result.stderr}")


@activity.defn
async def cleanup_sandbox(input: CleanupSandboxInput) -> None:
    """Cleanup sandbox. Safe to call even if sandbox doesn't exist."""
    try:
        sandbox = await SandboxEnvironment.get_by_id(input.sandbox_id)
        await sandbox.destroy()
    except NotFoundError:
        pass
    except Exception as e:
        logger.exception(f"Failed to cleanup sandbox {input.sandbox_id}: {e}")
        raise RuntimeError(f"Failed to cleanup sandbox {input.sandbox_id}: {e}")
