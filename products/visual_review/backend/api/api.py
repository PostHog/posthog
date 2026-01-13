"""
Facade API for visual_review.

This is the ONLY module other apps are allowed to import.

Responsibilities:
- Accept DTOs as input
- Call domain logic (logic.py)
- Convert Django models to DTOs before returning
- Remain thin and stable

Do NOT:
- Implement business logic here (use logic.py)
- Import DRF, serializers, or HTTP concerns
- Return ORM instances or QuerySets
"""

from uuid import UUID

from .. import logic
from .dtos import (
    ApproveRunInput,
    Artifact,
    CreateRunInput,
    CreateRunResult,
    Project,
    RegisterArtifactInput,
    Run,
    RunSummary,
    Snapshot,
    UploadUrl,
)

# Re-export exceptions for callers
ProjectNotFoundError = logic.ProjectNotFoundError
RunNotFoundError = logic.RunNotFoundError
ArtifactNotFoundError = logic.ArtifactNotFoundError


# --- Converters (model -> DTO) ---


def _to_artifact(artifact, project_id: UUID) -> Artifact:
    download_url = logic.get_presigned_download_url(project_id, artifact.content_hash)
    return Artifact(
        id=artifact.id,
        content_hash=artifact.content_hash,
        width=artifact.width,
        height=artifact.height,
        download_url=download_url,
    )


def _to_snapshot(snapshot, project_id: UUID) -> Snapshot:
    return Snapshot(
        id=snapshot.id,
        identifier=snapshot.identifier,
        result=snapshot.result,
        current_artifact=_to_artifact(snapshot.current_artifact, project_id) if snapshot.current_artifact else None,
        baseline_artifact=_to_artifact(snapshot.baseline_artifact, project_id) if snapshot.baseline_artifact else None,
        diff_artifact=_to_artifact(snapshot.diff_artifact, project_id) if snapshot.diff_artifact else None,
        diff_percentage=snapshot.diff_percentage,
        diff_pixel_count=snapshot.diff_pixel_count,
    )


def _to_run(run) -> Run:
    return Run(
        id=run.id,
        project_id=run.project_id,
        status=run.status,
        run_type=run.run_type,
        commit_sha=run.commit_sha,
        branch=run.branch,
        pr_number=run.pr_number,
        approved=run.approved,
        approved_at=run.approved_at,
        summary=RunSummary(
            total=run.total_snapshots,
            changed=run.changed_count,
            new=run.new_count,
            removed=run.removed_count,
            unchanged=run.total_snapshots - run.changed_count - run.new_count - run.removed_count,
        ),
        error_message=run.error_message or None,
        created_at=run.created_at,
        completed_at=run.completed_at,
    )


def _to_project(project) -> Project:
    return Project(
        id=project.id,
        team_id=project.team_id,
        name=project.name,
        created_at=project.created_at,
    )


# --- Project API ---


def get_project(project_id: UUID) -> Project:
    project = logic.get_project(project_id)
    return _to_project(project)


def list_projects(team_id: int) -> list[Project]:
    projects = logic.list_projects_for_team(team_id)
    return [_to_project(p) for p in projects]


def create_project(team_id: int, name: str) -> Project:
    project = logic.create_project(team_id=team_id, name=name)
    return _to_project(project)


# --- Artifact API ---


def get_upload_url(project_id: UUID, content_hash: str) -> UploadUrl | None:
    result = logic.get_presigned_upload_url(project_id, content_hash)
    if not result:
        return None
    return UploadUrl(url=result["url"], fields=result["fields"])


def register_artifact(input: RegisterArtifactInput) -> Artifact:
    artifact, _ = logic.get_or_create_artifact(
        project_id=input.project_id,
        content_hash=input.content_hash,
        storage_path=input.storage_path,
        width=input.width,
        height=input.height,
        size_bytes=input.size_bytes,
    )
    return _to_artifact(artifact, input.project_id)


# --- Run API ---


def create_run(input: CreateRunInput) -> CreateRunResult:
    snapshots = [{"identifier": s.identifier, "content_hash": s.content_hash} for s in input.snapshots]

    run, missing_hashes = logic.create_run(
        project_id=input.project_id,
        run_type=input.run_type,
        commit_sha=input.commit_sha,
        branch=input.branch,
        pr_number=input.pr_number,
        snapshots=snapshots,
        baseline_hashes=input.baseline_hashes,
    )

    return CreateRunResult(run_id=run.id, missing_hashes=missing_hashes)


def get_run(run_id: UUID) -> Run:
    run = logic.get_run(run_id)
    return _to_run(run)


def get_run_snapshots(run_id: UUID) -> list[Snapshot]:
    snapshots = logic.get_run_snapshots(run_id)
    if not snapshots:
        return []
    project_id = snapshots[0].run.project_id
    return [_to_snapshot(s, project_id) for s in snapshots]


def complete_run(run_id: UUID) -> Run:
    """Mark run as ready for diff processing."""
    logic.mark_run_processing(run_id)
    # Trigger diff task (will be implemented in tasks.py)
    from ..tasks.tasks import process_run_diffs

    process_run_diffs.delay(str(run_id))
    run = logic.get_run(run_id)
    return _to_run(run)


def approve_run(input: ApproveRunInput) -> Run:
    approved_snapshots = [{"identifier": s.identifier, "new_hash": s.new_hash} for s in input.snapshots]

    run = logic.approve_run(
        run_id=input.run_id,
        user_id=input.user_id,
        approved_snapshots=approved_snapshots,
    )
    return _to_run(run)
