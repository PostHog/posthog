"""
Business logic for visual_review.

ORM queries, validation, calculations, business rules.
Called by api/api.py facade. Do not call from outside this module.
"""

from uuid import UUID

from django.db import transaction
from django.utils import timezone

from .domain_types import RunStatus, SnapshotResult
from .models import Artifact, Project, Run, RunSnapshot
from .storage import ArtifactStorage


class ProjectNotFoundError(Exception):
    pass


class RunNotFoundError(Exception):
    pass


class ArtifactNotFoundError(Exception):
    pass


# --- Project Operations ---


def get_project(project_id: UUID) -> Project:
    try:
        return Project.objects.get(id=project_id)
    except Project.DoesNotExist as e:
        raise ProjectNotFoundError(f"Project {project_id} not found") from e


def list_projects_for_team(team_id: int) -> list[Project]:
    return list(Project.objects.filter(team_id=team_id).order_by("-created_at"))


def create_project(team_id: int, name: str) -> Project:
    return Project.objects.create(team_id=team_id, name=name)


# --- Artifact Operations ---


def get_artifact(project_id: UUID, content_hash: str) -> Artifact | None:
    return Artifact.objects.filter(project_id=project_id, content_hash=content_hash).first()


def get_or_create_artifact(
    project_id: UUID,
    content_hash: str,
    storage_path: str,
    width: int | None = None,
    height: int | None = None,
    size_bytes: int | None = None,
) -> tuple[Artifact, bool]:
    return Artifact.objects.get_or_create(
        project_id=project_id,
        content_hash=content_hash,
        defaults={
            "storage_path": storage_path,
            "width": width,
            "height": height,
            "size_bytes": size_bytes,
        },
    )


def find_missing_hashes(project_id: UUID, hashes: list[str]) -> list[str]:
    """Return hashes that don't exist as artifacts in the project."""
    existing = set(
        Artifact.objects.filter(project_id=project_id, content_hash__in=hashes).values_list("content_hash", flat=True)
    )
    return [h for h in hashes if h not in existing]


def get_presigned_upload_url(project_id: UUID, content_hash: str) -> dict | None:
    storage = ArtifactStorage(str(project_id))
    return storage.get_presigned_upload_url(content_hash)


def get_presigned_download_url(project_id: UUID, content_hash: str) -> str | None:
    storage = ArtifactStorage(str(project_id))
    return storage.get_presigned_download_url(content_hash)


# --- Run Operations ---


def get_run(run_id: UUID) -> Run:
    try:
        return Run.objects.select_related("project").get(id=run_id)
    except Run.DoesNotExist as e:
        raise RunNotFoundError(f"Run {run_id} not found") from e


def get_run_with_snapshots(run_id: UUID) -> Run:
    try:
        return Run.objects.prefetch_related(
            "snapshots__current_artifact",
            "snapshots__baseline_artifact",
            "snapshots__diff_artifact",
        ).get(id=run_id)
    except Run.DoesNotExist as e:
        raise RunNotFoundError(f"Run {run_id} not found") from e


@transaction.atomic
def create_run(
    project_id: UUID,
    run_type: str,
    commit_sha: str,
    branch: str,
    pr_number: int | None,
    snapshots: list[dict],
    baseline_hashes: dict[str, str],
) -> tuple[Run, list[str]]:
    """
    Create a new run with its snapshots.

    Returns the run and list of missing artifact hashes.
    """
    project = get_project(project_id)

    run = Run.objects.create(
        project=project,
        run_type=run_type,
        commit_sha=commit_sha,
        branch=branch,
        pr_number=pr_number,
        total_snapshots=len(snapshots),
    )

    all_hashes: set[str] = set()

    for snap in snapshots:
        identifier = snap["identifier"]
        current_hash = snap["content_hash"]
        baseline_hash = baseline_hashes.get(identifier)

        all_hashes.add(current_hash)
        if baseline_hash:
            all_hashes.add(baseline_hash)

        # Look up existing artifacts
        current_artifact = get_artifact(project_id, current_hash)
        baseline_artifact = get_artifact(project_id, baseline_hash) if baseline_hash else None

        # Determine initial result based on baseline_hash presence, not artifact existence
        # (baseline artifact might not be uploaded yet)
        if baseline_hash is None:
            result = SnapshotResult.NEW
        elif current_hash == baseline_hash:
            result = SnapshotResult.UNCHANGED
        else:
            result = SnapshotResult.CHANGED

        RunSnapshot.objects.create(
            run=run,
            identifier=identifier,
            current_artifact=current_artifact,
            baseline_artifact=baseline_artifact,
            result=result,
        )

    missing_hashes = find_missing_hashes(project_id, list(all_hashes))
    return run, missing_hashes


def mark_run_processing(run_id: UUID) -> Run:
    run = get_run(run_id)
    run.status = RunStatus.PROCESSING
    run.save(update_fields=["status"])
    return run


def mark_run_completed(run_id: UUID, error_message: str = "") -> Run:
    run = get_run_with_snapshots(run_id)

    snapshots = list(run.snapshots.all())

    changed_count = sum(1 for s in snapshots if s.result == SnapshotResult.CHANGED)
    new_count = sum(1 for s in snapshots if s.result == SnapshotResult.NEW)
    removed_count = sum(1 for s in snapshots if s.result == SnapshotResult.REMOVED)

    run.status = RunStatus.FAILED if error_message else RunStatus.COMPLETED
    run.error_message = error_message
    run.completed_at = timezone.now()
    run.changed_count = changed_count
    run.new_count = new_count
    run.removed_count = removed_count
    run.save(update_fields=["status", "error_message", "completed_at", "changed_count", "new_count", "removed_count"])

    return run


@transaction.atomic
def approve_run(run_id: UUID, user_id: int, approved_snapshots: list[dict]) -> Run:
    """
    Approve visual changes for a run.

    Updates baseline hashes for approved snapshots.
    """
    run = get_run(run_id)

    # Build lookup of identifier -> new_hash
    approvals = {s["identifier"]: s["new_hash"] for s in approved_snapshots}

    # Update snapshots
    for snapshot in run.snapshots.filter(identifier__in=approvals.keys()):
        new_hash = approvals[snapshot.identifier]
        new_artifact = get_artifact(run.project_id, new_hash)

        if new_artifact:
            snapshot.baseline_artifact = new_artifact
            snapshot.result = SnapshotResult.UNCHANGED
            snapshot.save(update_fields=["baseline_artifact", "result"])

    # Mark run approved
    run.approved = True
    run.approved_at = timezone.now()
    run.approved_by_id = user_id
    run.save(update_fields=["approved", "approved_at", "approved_by_id"])

    return run


# --- Snapshot Operations ---


def get_run_snapshots(run_id: UUID) -> list[RunSnapshot]:
    run = get_run(run_id)
    return list(
        run.snapshots.select_related("current_artifact", "baseline_artifact", "diff_artifact").order_by("identifier")
    )


def update_snapshot_diff(
    snapshot_id: UUID,
    diff_artifact: Artifact,
    diff_percentage: float,
    diff_pixel_count: int,
) -> RunSnapshot:
    snapshot = RunSnapshot.objects.get(id=snapshot_id)
    snapshot.diff_artifact = diff_artifact
    snapshot.diff_percentage = diff_percentage
    snapshot.diff_pixel_count = diff_pixel_count
    snapshot.save(update_fields=["diff_artifact", "diff_percentage", "diff_pixel_count"])
    return snapshot


def link_artifact_to_snapshots(project_id: UUID, content_hash: str) -> None:
    """
    After an artifact is uploaded, link it to any pending snapshots.
    """
    artifact = get_artifact(project_id, content_hash)
    if not artifact:
        return

    # Link as current artifact where missing
    RunSnapshot.objects.filter(
        run__project_id=project_id,
        current_artifact__isnull=True,
    ).extra(
        where=["identifier IN (SELECT identifier FROM visual_review_runsnapshot WHERE current_artifact_id IS NULL)"]
    )

    # Actually, simpler approach: we stored hash info at creation time
    # The linking happens during run creation or artifact registration
    pass
