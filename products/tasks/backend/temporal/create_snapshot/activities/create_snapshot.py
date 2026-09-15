import shlex
import logging
from dataclasses import dataclass

from temporalio import activity

from posthog.temporal.common.utils import asyncify

from products.tasks.backend.constants import SNAPSHOT_KIND_FILESYSTEM
from products.tasks.backend.logic.services.sandbox import SandboxBase, get_sandbox_class_for_sandbox_id
from products.tasks.backend.models import SandboxSnapshot
from products.tasks.backend.temporal.observability import log_activity_execution

from .get_snapshot_context import SnapshotContext

logger = logging.getLogger(__name__)


@dataclass
class CreateSnapshotInput:
    context: SnapshotContext
    sandbox_id: str


def _scrub_clone_credentials(sandbox: SandboxBase, repository: str) -> None:
    """Reset the clone's remote to a token-less URL before the snapshot captures it.

    The clone embeds a short-lived installation token in the origin URL; a snapshot
    must not persist it. Restored runs re-point origin with a fresh token before
    fetching (see checkout_branch_in_sandbox).
    """
    org, repo = repository.lower().split("/")
    repo_path = f"/tmp/workspace/repos/{org}/{repo}"
    result = sandbox.execute(
        f"cd {shlex.quote(repo_path)} && git remote set-url origin https://github.com/{org}/{repo}.git",
        timeout_seconds=30,
    )
    if result.exit_code != 0:
        raise RuntimeError(f"Failed to scrub clone credentials before snapshot: {result.stderr[:200]}")


def _delete_superseded_snapshots(ctx: SnapshotContext, new_snapshot: SandboxSnapshot) -> None:
    """Best-effort: keep one snapshot per (integration, repos, backend) generation."""
    candidates = SandboxSnapshot.objects.filter(
        integration_id=ctx.github_integration_id,
        created_at__lt=new_snapshot.created_at,
    ).exclude(id=new_snapshot.id)
    target_repos = sorted(repo.lower() for repo in new_snapshot.repos)
    for snapshot in candidates:
        if snapshot.sandbox_backend != ctx.sandbox_backend:
            continue
        if sorted(repo.lower() for repo in snapshot.repos) != target_repos:
            continue
        try:
            snapshot.delete()
        except Exception:
            logger.exception(
                "Failed to delete superseded sandbox snapshot",
                extra={"snapshot_id": str(snapshot.id), "external_id": snapshot.external_id},
            )


@activity.defn
@asyncify
def create_snapshot(input: CreateSnapshotInput) -> str:
    ctx = input.context

    with log_activity_execution(
        "create_snapshot",
        sandbox_id=input.sandbox_id,
        **ctx.to_log_context(),
    ):
        sandbox = get_sandbox_class_for_sandbox_id(input.sandbox_id).get_by_id(input.sandbox_id)

        _scrub_clone_credentials(sandbox, ctx.repository)

        snapshot_external_id = sandbox.create_snapshot()

        snapshot = SandboxSnapshot.objects.create(
            integration_id=ctx.github_integration_id,
            repos=[ctx.repository],
            external_id=snapshot_external_id,
            status=SandboxSnapshot.Status.COMPLETE,
            metadata={
                "sandbox_backend": ctx.sandbox_backend,
                "snapshot_kind": SNAPSHOT_KIND_FILESYSTEM,
            },
        )

        _delete_superseded_snapshots(ctx, snapshot)

        return str(snapshot.id)
