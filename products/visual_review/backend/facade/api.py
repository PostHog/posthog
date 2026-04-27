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

from django.contrib.auth import get_user_model

from .. import logic
from . import contracts
from .enums import ReviewDecision

User = get_user_model()

# Re-export exceptions for callers
RepoNotFoundError = logic.RepoNotFoundError
RunNotFoundError = logic.RunNotFoundError
ArtifactNotFoundError = logic.ArtifactNotFoundError
GitHubIntegrationNotFoundError = logic.GitHubIntegrationNotFoundError
GitHubCommitError = logic.GitHubCommitError
PRSHAMismatchError = logic.PRSHAMismatchError
StaleRunError = logic.StaleRunError
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


def _to_snapshot(
    snapshot, repo_id: UUID, user_basic_infos: dict[int, contracts.UserBasicInfo] | None = None
) -> contracts.Snapshot:
    reviewed_by = (user_basic_infos or {}).get(snapshot.reviewed_by_id) if snapshot.reviewed_by_id else None
    return contracts.Snapshot(
        id=snapshot.id,
        identifier=snapshot.identifier,
        result=snapshot.result,
        classification_reason=snapshot.classification_reason or "",
        current_artifact=_to_artifact(snapshot.current_artifact, repo_id) if snapshot.current_artifact else None,
        baseline_artifact=_to_artifact(snapshot.baseline_artifact, repo_id) if snapshot.baseline_artifact else None,
        diff_artifact=_to_artifact(snapshot.diff_artifact, repo_id) if snapshot.diff_artifact else None,
        diff_percentage=snapshot.diff_percentage,
        diff_pixel_count=snapshot.diff_pixel_count,
        review_state=snapshot.review_state,
        reviewed_at=snapshot.reviewed_at,
        approved_hash=snapshot.approved_hash,
        tolerated_hash_id=snapshot.tolerated_hash_match_id,
        is_quarantined=snapshot.is_quarantined,
        reviewed_by=reviewed_by,
        metadata=snapshot.metadata or {},
    )


def _compute_unresolved(run) -> int:
    """Compute unresolved count from prefetched snapshots, or fall back to DB."""
    # Use prefetched snapshots if available (detail view), skip for list views
    if "snapshots" in getattr(run, "_prefetched_objects_cache", {}):
        return sum(1 for s in run.snapshots.all() if logic._is_unresolved(s))
    return 0


def _to_run(run, user_basic_infos: dict[int, contracts.UserBasicInfo] | None = None) -> contracts.Run:
    approved_by = (user_basic_infos or {}).get(run.approved_by_id) if run.approved_by_id else None
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
            unresolved=_compute_unresolved(run),
            tolerated_matched=run.tolerated_match_count,
        ),
        error_message=run.error_message or None,
        created_at=run.created_at,
        completed_at=run.completed_at,
        is_stale=logic.is_run_stale(run),
        superseded_by_id=run.superseded_by_id,
        approved_by=approved_by,
        metadata=run.metadata or {},
    )


def _to_repo(repo) -> contracts.Repo:
    return contracts.Repo(
        id=repo.id,
        team_id=repo.team_id,
        repo_external_id=repo.repo_external_id,
        repo_full_name=repo.repo_full_name,
        baseline_file_paths=repo.baseline_file_paths,
        enable_pr_comments=repo.enable_pr_comments,
        created_at=repo.created_at,
    )


# --- Repo API ---


def get_repo(repo_id: UUID, team_id: int) -> contracts.Repo:
    repo = logic.get_repo(repo_id, team_id)
    return _to_repo(repo)


def list_repos(team_id: int) -> list[contracts.Repo]:
    projects = logic.list_repos_for_team(team_id)
    return [_to_repo(p) for p in projects]


def create_repo(team_id: int, repo_external_id: int, repo_full_name: str) -> contracts.Repo:
    repo = logic.create_repo(team_id=team_id, repo_external_id=repo_external_id, repo_full_name=repo_full_name)
    return _to_repo(repo)


def update_repo(input: contracts.UpdateRepoInput, team_id: int) -> contracts.Repo:
    repo = logic.update_repo(
        repo_id=input.repo_id,
        team_id=team_id,
        baseline_file_paths=input.baseline_file_paths,
        enable_pr_comments=input.enable_pr_comments,
    )
    return _to_repo(repo)


# --- Run API ---


def list_runs(team_id: int, review_state: str | None = None) -> list[contracts.Run]:
    runs = logic.list_runs_for_team(team_id, review_state=review_state)
    return [_to_run(r) for r in runs]


def get_review_state_counts(team_id: int) -> dict[str, int]:
    return logic.get_review_state_counts(team_id)


def create_run(input: contracts.CreateRunInput, team_id: int) -> contracts.CreateRunResult:
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
        team_id=team_id,
        run_type=input.run_type,
        commit_sha=input.commit_sha,
        branch=input.branch,
        pr_number=input.pr_number,
        snapshots=snapshots,
        baseline_hashes=input.baseline_hashes,
        unchanged_count=input.unchanged_count,
        removed_identifiers=list(input.removed_identifiers),
        purpose=input.purpose,
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


def add_snapshots(input: contracts.AddSnapshotsInput, run_id: UUID, team_id: int) -> contracts.AddSnapshotsResult:
    """Add a batch of snapshots to an existing run (shard-based flow)."""
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

    added, uploads = logic.add_snapshots_to_run(
        run_id=run_id,
        team_id=team_id,
        snapshots=snapshots,
        baseline_hashes=input.baseline_hashes,
    )

    upload_targets = [
        contracts.UploadTarget(content_hash=u["content_hash"], url=u["url"], fields=u["fields"]) for u in uploads
    ]

    return contracts.AddSnapshotsResult(added=added, uploads=upload_targets)


def get_run(run_id: UUID, team_id: int | None = None) -> contracts.Run:
    run = logic.get_run_with_snapshots(run_id, team_id=team_id)
    user_ids = {run.approved_by_id} if run.approved_by_id else set()
    user_basic_infos = _fetch_user_basic_infos(user_ids)
    return _to_run(run, user_basic_infos)


def get_run_snapshots(run_id: UUID, team_id: int | None = None) -> list[contracts.Snapshot]:
    snapshots = logic.get_run_snapshots(run_id, team_id=team_id)
    if not snapshots:
        return []
    repo_id = snapshots[0].run.repo_id
    user_ids = {s.reviewed_by_id for s in snapshots if s.reviewed_by_id}
    user_basic_infos = _fetch_user_basic_infos(user_ids)
    return [_to_snapshot(s, repo_id, user_basic_infos) for s in snapshots]


def get_snapshot_history(repo_id: UUID, identifier: str) -> list[contracts.SnapshotHistoryEntry]:
    entries = logic.get_snapshot_history(repo_id, identifier)
    return [
        contracts.SnapshotHistoryEntry(
            run_id=e["run_id"],
            result=e["result"],
            branch=e["branch"],
            commit_sha=e["commit_sha"],
            created_at=e["created_at"],
        )
        for e in entries
    ]


def mark_snapshot_as_tolerated(run_id: UUID, snapshot_id: UUID, user_id: int, team_id: int) -> contracts.Snapshot:
    snapshot = logic.mark_snapshot_as_tolerated(run_id, snapshot_id, user_id, team_id)
    return _to_snapshot(snapshot, snapshot.run.repo_id)


def get_tolerated_hashes(repo_id: UUID, identifier: str) -> list[contracts.ToleratedHashEntry]:
    entries = logic.get_tolerated_hashes_for_identifier(repo_id, identifier)
    return [
        contracts.ToleratedHashEntry(
            id=e.id,
            alternate_hash=e.alternate_hash,
            baseline_hash=e.baseline_hash,
            reason=e.reason,
            diff_percentage=e.diff_percentage,
            created_at=e.created_at,
            source_run_id=e.source_run_id,
        )
        for e in entries
    ]


def complete_run(run_id: UUID, team_id: int | None = None) -> contracts.Run:
    """
    Complete a run: detect removals, verify uploads, trigger diff processing.
    """
    if team_id is not None:
        logic.get_run(run_id, team_id=team_id)  # validates ownership
    run = logic.complete_run(run_id)
    return _to_run(run)


def recompute_run(run_id: UUID, team_id: int | None = None) -> contracts.RecomputeResult:
    result = logic.recompute_run(run_id, team_id=team_id)
    run = logic.get_run_with_snapshots(run_id, team_id=team_id)
    return contracts.RecomputeResult(
        run=_to_run(run),
        counts_changed=result["counts_changed"],
        unresolved=result["unresolved"],
        ci_rerun_triggered=result["ci_rerun_triggered"],
        ci_rerun_error=result["ci_rerun_error"],
    )


def approve_all(
    run_id: UUID,
    user_id: int,
    team_id: int | None = None,
    review_decision: ReviewDecision = ReviewDecision.HUMAN_APPROVED,
    commit_to_github: bool = True,
) -> contracts.AutoApproveResult:
    run, baseline_content = logic.approve_all(
        run_id=run_id,
        user_id=user_id,
        team_id=team_id,
        review_decision=review_decision,
        commit_to_github=commit_to_github,
    )
    return contracts.AutoApproveResult(
        run=_to_run(run),
        baseline_content=baseline_content,
    )


def approve_run(input: contracts.ApproveRunInput, team_id: int | None = None) -> contracts.Run:
    """Approve specific snapshots (DB only).

    For full run finalization with GitHub commit, use approve_all=true
    which routes through auto_approve_run.
    """
    approved_snapshots = [{"identifier": s.identifier, "new_hash": s.new_hash} for s in input.snapshots]
    run = logic.approve_snapshots(
        run_id=input.run_id,
        user_id=input.user_id,
        approved_snapshots=approved_snapshots,
        team_id=team_id,
    )
    return _to_run(run)


# --- Quarantine ---


def _to_user_basic(user) -> contracts.UserBasicInfo:
    return contracts.UserBasicInfo(
        id=user.id,
        first_name=user.first_name,
        email=user.email,
    )


def _fetch_user_basic_infos(user_ids: set[int]) -> dict[int, contracts.UserBasicInfo]:
    if not user_ids:
        return {}
    users = User.objects.filter(id__in=user_ids).only("id", "first_name", "email")
    return {u.id: _to_user_basic(u) for u in users}


def _to_quarantined_entry(
    q, user_basic_infos: dict[int, contracts.UserBasicInfo] | None = None
) -> contracts.QuarantinedIdentifierEntry:
    created_by = (user_basic_infos or {}).get(q.created_by_id) if q.created_by_id else None
    return contracts.QuarantinedIdentifierEntry(
        id=q.id,
        identifier=q.identifier,
        run_type=q.run_type,
        reason=q.reason,
        expires_at=q.expires_at,
        created_at=q.created_at,
        updated_at=q.updated_at,
        created_by=created_by,
    )


def list_quarantined(
    repo_id: UUID, team_id: int, identifier: str | None = None, run_type: str | None = None
) -> list[contracts.QuarantinedIdentifierEntry]:
    entries = logic.list_quarantined_identifiers(repo_id, team_id, identifier=identifier, run_type=run_type)
    user_ids = {e.created_by_id for e in entries if e.created_by_id}
    user_basic_infos = _fetch_user_basic_infos(user_ids)
    return [_to_quarantined_entry(q, user_basic_infos) for q in entries]


def quarantine_identifier(
    repo_id: UUID, run_type: str, input: contracts.QuarantineInput, user_id: int, team_id: int
) -> contracts.QuarantinedIdentifierEntry:
    entry = logic.quarantine_identifier(
        repo_id=repo_id,
        identifier=input.identifier,
        run_type=run_type,
        reason=input.reason,
        expires_at=input.expires_at,
        user_id=user_id,
        team_id=team_id,
    )
    user_basic_infos = _fetch_user_basic_infos({user_id})
    return _to_quarantined_entry(entry, user_basic_infos)


def unquarantine_identifier(repo_id: UUID, identifier: str, run_type: str, team_id: int) -> None:
    logic.unquarantine_identifier(repo_id=repo_id, identifier=identifier, run_type=run_type, team_id=team_id)


def expire_quarantine_entry(entry_id: UUID, team_id: int) -> None:
    logic.expire_quarantine_entry(entry_id=entry_id, team_id=team_id)
