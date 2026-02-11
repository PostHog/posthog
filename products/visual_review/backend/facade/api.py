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
from . import contracts

# Re-export exceptions for callers
RepoNotFoundError = logic.RepoNotFoundError
RunNotFoundError = logic.RunNotFoundError
ArtifactNotFoundError = logic.ArtifactNotFoundError
GitHubIntegrationNotFoundError = logic.GitHubIntegrationNotFoundError
GitHubCommitError = logic.GitHubCommitError
PRSHAMismatchError = logic.PRSHAMismatchError
BaselineFilePathNotConfiguredError = logic.BaselineFilePathNotConfiguredError


# --- Converters (model -> DTO) ---
#
# These look repetitive when fields align 1:1. The value is having ONE place
# where "internal" becomes "external contract". When models and DTOs drift,
# the mapper absorbs the change instead of it leaking everywhere.


def _to_artifact(artifact, repo_id: UUID) -> contracts.Artifact:
    download_url = logic.get_presigned_download_url(repo_id, artifact.content_hash)
    return contracts.Artifact(
        id=artifact.id,
        content_hash=artifact.content_hash,
        width=artifact.width,
        height=artifact.height,
        download_url=download_url,
    )


def _to_snapshot(snapshot, repo_id: UUID) -> contracts.Snapshot:
    return contracts.Snapshot(
        id=snapshot.id,
        identifier=snapshot.identifier,
        result=snapshot.result,
        current_artifact=_to_artifact(snapshot.current_artifact, repo_id) if snapshot.current_artifact else None,
        baseline_artifact=_to_artifact(snapshot.baseline_artifact, repo_id) if snapshot.baseline_artifact else None,
        diff_artifact=_to_artifact(snapshot.diff_artifact, repo_id) if snapshot.diff_artifact else None,
        diff_percentage=snapshot.diff_percentage,
        diff_pixel_count=snapshot.diff_pixel_count,
        review_state=snapshot.review_state,
        reviewed_at=snapshot.reviewed_at,
        approved_hash=snapshot.approved_hash,
        metadata=snapshot.metadata or {},
    )


def _to_run(run) -> contracts.Run:
    return contracts.Run(
        id=run.id,
        repo_id=run.repo_id,
        status=run.status,
        run_type=run.run_type,
        commit_sha=run.commit_sha,
        branch=run.branch,
        pr_number=run.pr_number,
        approved=run.approved,
        approved_at=run.approved_at,
        summary=contracts.RunSummary(
            total=run.total_snapshots,
            changed=run.changed_count,
            new=run.new_count,
            removed=run.removed_count,
            unchanged=run.total_snapshots - run.changed_count - run.new_count - run.removed_count,
        ),
        error_message=run.error_message or None,
        created_at=run.created_at,
        completed_at=run.completed_at,
        metadata=run.metadata or {},
    )


def _to_repo(repo) -> contracts.Repo:
    return contracts.Repo(
        id=repo.id,
        team_id=repo.team_id,
        name=repo.name,
        repo_full_name=repo.repo_full_name,
        baseline_file_paths=repo.baseline_file_paths,
        created_at=repo.created_at,
    )


# --- Repo API ---


def get_repo(repo_id: UUID) -> contracts.Repo:
    repo = logic.get_repo(repo_id)
    return _to_repo(repo)


def list_repos(team_id: int) -> list[contracts.Repo]:
    projects = logic.list_repos_for_team(team_id)
    return [_to_repo(p) for p in projects]


def create_repo(team_id: int, name: str) -> contracts.Repo:
    repo = logic.create_repo(team_id=team_id, name=name)
    return _to_repo(repo)


def update_repo(input: contracts.UpdateRepoInput) -> contracts.Repo:
    repo = logic.update_repo(
        repo_id=input.repo_id,
        name=input.name,
        repo_full_name=input.repo_full_name,
        baseline_file_paths=input.baseline_file_paths,
    )
    return _to_repo(repo)


# --- Run API ---


def list_runs(team_id: int) -> list[contracts.Run]:
    """List all runs for a team across all projects."""
    runs = logic.list_runs_for_team(team_id)
    return [_to_run(r) for r in runs]


def create_run(input: contracts.CreateRunInput) -> contracts.CreateRunResult:
    snapshots = [
        {
            "identifier": s.identifier,
            "content_hash": s.content_hash,
            "width": s.width,
            "height": s.height,
            "metadata": dict(s.metadata) if s.metadata else {},
        }
        for s in input.snapshots
    ]

    run, uploads = logic.create_run(
        repo_id=input.repo_id,
        run_type=input.run_type,
        commit_sha=input.commit_sha,
        branch=input.branch,
        pr_number=input.pr_number,
        snapshots=snapshots,
        baseline_hashes=input.baseline_hashes,
        metadata=dict(input.metadata) if input.metadata else {},
    )

    upload_targets = [
        contracts.UploadTarget(
            content_hash=u["content_hash"],
            url=u["url"],
            fields=u["fields"],
        )
        for u in uploads
    ]

    return contracts.CreateRunResult(run_id=run.id, uploads=upload_targets)


def get_run(run_id: UUID) -> contracts.Run:
    run = logic.get_run(run_id)
    return _to_run(run)


def get_run_snapshots(run_id: UUID) -> list[contracts.Snapshot]:
    snapshots = logic.get_run_snapshots(run_id)
    if not snapshots:
        return []
    repo_id = snapshots[0].run.repo_id
    return [_to_snapshot(s, repo_id) for s in snapshots]


def complete_run(run_id: UUID) -> contracts.Run:
    """
    Complete a run: verify uploads, create artifacts, trigger diff processing.
    """
    run = logic.complete_run(run_id)
    return _to_run(run)


def approve_run(input: contracts.ApproveRunInput) -> contracts.Run:
    approved_snapshots = [{"identifier": s.identifier, "new_hash": s.new_hash} for s in input.snapshots]

    run = logic.approve_run(
        run_id=input.run_id,
        user_id=input.user_id,
        approved_snapshots=approved_snapshots,
        commit_to_github=input.commit_to_github,
    )
    return _to_run(run)
