from asgiref.sync import sync_to_async
from temporalio import activity

from products.tasks.backend.models import SandboxSnapshot
from products.tasks.backend.temporal.sandbox.activity_schemas import (
    CheckRepoInSnapshotInput,
    CheckRepoInSnapshotOutput,
    GetBaseSnapshotInput,
    GetBaseSnapshotOutput,
    SetupRepoInSnapshotInput,
    SetupRepoInSnapshotOutput,
)


@activity.defn
async def get_base_snapshot_for_integration_activity(input: GetBaseSnapshotInput) -> GetBaseSnapshotOutput:
    """Get or create the base snapshot for a GitHub integration."""
    # Get latest complete snapshot
    snapshot = await sync_to_async(SandboxSnapshot.get_latest_complete)(input.github_integration_id)

    is_new = False
    if not snapshot:
        # Create new base snapshot (no repos yet)
        # TODO: Create base Runloop blueprint with CLI + tools
        base_external_id = "base_blueprint_TODO"  # Placeholder until we implement Runloop integration

        snapshot = await sync_to_async(SandboxSnapshot.objects.create)(
            integration_id=input.github_integration_id,
            repos=[],
            external_id=base_external_id,
            status=SandboxSnapshot.Status.COMPLETE,
        )
        is_new = True

    return GetBaseSnapshotOutput(
        snapshot_id=str(snapshot.id),
        external_id=snapshot.external_id,
        repos=snapshot.repos,
        status=snapshot.status,
        is_new=is_new,
    )


@activity.defn
async def check_repo_in_snapshot_activity(input: CheckRepoInSnapshotInput) -> CheckRepoInSnapshotOutput:
    """Check if a repository exists in the latest complete snapshot."""
    # Get latest complete snapshot with required repo
    snapshot = await sync_to_async(SandboxSnapshot.get_latest_snapshot_with_repos)(
        input.github_integration_id, [input.repository], status=SandboxSnapshot.Status.COMPLETE
    )

    if snapshot:
        return CheckRepoInSnapshotOutput(exists=True, snapshot_id=str(snapshot.id))

    return CheckRepoInSnapshotOutput(exists=False, snapshot_id=None)


@activity.defn
async def setup_repo_in_snapshot_activity(input: SetupRepoInSnapshotInput) -> SetupRepoInSnapshotOutput:
    """Add a new repository to the integration's snapshot (creates NEW snapshot)."""

    base_snapshot = await sync_to_async(SandboxSnapshot.get_latest_snapshot_for_integration)(
        input.github_integration_id, status=SandboxSnapshot.Status.COMPLETE
    )

    # Create NEW snapshot record (many-to-one, no locking needed!)
    base_repos = base_snapshot.repos if base_snapshot else []
    new_repos = [*base_repos, input.repository]

    new_snapshot = await sync_to_async(SandboxSnapshot.objects.create)(
        integration_id=input.github_integration_id,
        repos=new_repos,
        status=SandboxSnapshot.Status.IN_PROGRESS,
        external_id=base_snapshot.external_id if base_snapshot else "TODO: Create base snapshot",
    )

    try:
        # TODO: Implement actual sandbox setup flow:
        # 1. Create sandbox from base snapshot
        # 2. Clone repository
        # 3. Run @posthog/code-agent with setup prompt
        # 4. Create Runloop snapshot
        # 5. Update new_snapshot with external_id and mark complete

        # Placeholder implementation
        new_external_id = f"snapshot_{new_snapshot.id}_TODO"
        setup_logs = "TODO: Implement actual setup"

        # Mark snapshot as complete
        await sync_to_async(new_snapshot.update_status)(SandboxSnapshot.Status.COMPLETE)
        new_snapshot.external_id = new_external_id
        await sync_to_async(new_snapshot.save)(update_fields=["external_id"])

        return SetupRepoInSnapshotOutput(
            success=True, new_external_id=new_external_id, setup_logs=setup_logs, error=None
        )

    except Exception as e:
        # Mark snapshot as error
        error_msg = str(e)
        await sync_to_async(new_snapshot.update_status)(SandboxSnapshot.Status.ERROR)

        return SetupRepoInSnapshotOutput(success=False, new_external_id="", setup_logs="", error=error_msg)
