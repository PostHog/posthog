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

from posthog.helpers.trigram_search import search_match_type_from_instance

from .. import logic
from ..diff_metadata import DiffMetadata
from . import contracts
from .enums import RunPurpose

User = get_user_model()

# Server-owned run.metadata keys — never accept these from client input.
# Allowing clients to set these would let them target arbitrary GitHub
# comments for PATCH, or spoof baseline commit SHAs in the audit trail.
# These are all written by the server itself, never by the CI runner.
# `github_check_run_id` is deliberately NOT reserved: the CI runner is its
# only source (from `JOB_CHECK_RUN_ID=${{ job.check_run_id }}`), and the
# rerun it enables is fenced by `_rerun_github_job` — the job must run on the
# run's commit and belong to the recorded workflow run (`github_run_id`).
_RESERVED_RUN_METADATA_KEYS = frozenset(
    {
        "github_comment_id",
        "baseline_commit_sha",
        "baseline_healed_from_merge_base",
    }
)

# GitHub identifiers arrive as JSON, so a client can send them as numbers.
# Store them as strings so rerun logic (which calls `.isdigit()`) and
# workflow-run comparisons stay type-stable.
_STRING_RUN_METADATA_KEYS = frozenset({"github_check_run_id", "github_run_id"})


def _sanitize_run_metadata(metadata: dict | None) -> dict:
    if not metadata:
        return {}
    cleaned = {k: v for k, v in metadata.items() if k not in _RESERVED_RUN_METADATA_KEYS}
    for key in _STRING_RUN_METADATA_KEYS:
        if cleaned.get(key) is not None:
            cleaned[key] = str(cleaned[key])
    return cleaned


# Re-export exceptions for callers
RepoNotFoundError = logic.RepoNotFoundError
RunNotFoundError = logic.RunNotFoundError
ArtifactNotFoundError = logic.ArtifactNotFoundError
GitHubIntegrationNotFoundError = logic.GitHubIntegrationNotFoundError
GitHubCommitError = logic.GitHubCommitError
GitHubRateLimitError = logic.GitHubRateLimitError
PRSHAMismatchError = logic.PRSHAMismatchError
StaleRunError = logic.StaleRunError
RunNotFullyResolvedError = logic.RunNotFullyResolvedError
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


def _parse_diff_metadata(
    diff_metadata_raw: dict | None,
) -> tuple[contracts.ClusterSummary | None, bool]:
    """Translate the compact storage shape into the verbose wire shape.

    Returns `(cluster_summary, size_mismatch)`. The cluster_summary side
    is None for legacy rows and identical-pair rows; size_mismatch
    defaults to False everywhere it isn't explicitly recorded.
    """
    if not diff_metadata_raw:
        return None, False
    parsed = DiffMetadata.model_validate(diff_metadata_raw)
    cluster_summary: contracts.ClusterSummary | None = None
    if parsed.cluster_summary is not None:
        cs = parsed.cluster_summary
        cluster_summary = contracts.ClusterSummary(
            items=[
                contracts.DiffCluster(
                    x=c.bbox[0],
                    y=c.bbox[1],
                    width=c.bbox[2],
                    height=c.bbox[3],
                    pixel_count=c.px,
                    centroid_x=c.centroid[0],
                    centroid_y=c.centroid[1],
                )
                for c in cs.items
            ],
            total=cs.total,
            truncated=cs.truncated,
        )
    return cluster_summary, parsed.size_mismatch


def _to_snapshot(
    snapshot, repo_id: UUID, user_basic_infos: dict[int, contracts.UserBasicInfo] | None = None
) -> contracts.Snapshot:
    reviewed_by = (user_basic_infos or {}).get(snapshot.reviewed_by_id) if snapshot.reviewed_by_id else None
    cluster_summary, size_mismatch = _parse_diff_metadata(snapshot.diff_metadata)
    return contracts.Snapshot(
        id=snapshot.id,
        run_id=snapshot.run_id,
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
        ssim_score=snapshot.ssim_score,
        change_kind=snapshot.change_kind or "",
        cluster_summary=cluster_summary,
        size_mismatch=size_mismatch,
    )


def _compute_unresolved(run) -> int:
    """Count snapshots still awaiting human resolution.

    Observe (tracking-only) runs are never approvable, so nothing is ever
    "unresolved" — return 0. This keeps the CLI (which exits non-zero when
    unresolved > 0) and the UI from treating a default-branch run as gating,
    matching the green commit status such runs post.
    """
    if run.purpose == RunPurpose.OBSERVE:
        return 0
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
        # Present only when the queryset came from a trigram search (annotation absent otherwise).
        search_match_type=search_match_type_from_instance(run),
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


def get_thumbnail_hash_for_identifier(repo_id: UUID, identifier: str) -> str | None:
    """Resolve a snapshot identifier to the content hash of its thumbnail, if any."""
    return logic.get_thumbnail_hash_for_identifier(repo_id, identifier)


def read_thumbnail_bytes(repo_id: UUID, content_hash: str) -> bytes | None:
    """Read the raw bytes for a thumbnail artifact from storage."""
    return logic.read_thumbnail_bytes(repo_id, content_hash)


def get_baselines_overview(repo_id: UUID) -> contracts.BaselineOverview:
    """Universe of identifiers with a current baseline, plus aggregates.

    Backs the snapshots overview page. See `logic.get_baselines_overview` for
    query shape and performance notes.
    """
    raw = logic.get_baselines_overview(repo_id)

    # Hydrate UserBasicInfo for everyone who created an active quarantine so the
    # overview can show "Quarantined by X" without a per-card fetch.
    quarantine_user_ids = {q.created_by_id for q in raw.active_quarantines_by_key.values() if q.created_by_id}
    quarantine_user_infos = _fetch_user_basic_infos(quarantine_user_ids)

    entries: list[contracts.BaselineEntry] = []
    for snapshot in raw.entries:
        identifier = snapshot.identifier
        run = snapshot.run
        artifact = snapshot.current_artifact
        thumbnail = artifact.thumbnail if artifact is not None else None
        # `(run_type, identifier)` keys because the same identifier in
        # different run types is a different baseline.
        key = (run.run_type, identifier)
        metadata = snapshot.metadata or {}
        active_quarantine = raw.active_quarantines_by_key.get(key)
        entries.append(
            contracts.BaselineEntry(
                identifier=identifier,
                run_type=run.run_type,
                browser=metadata.get("browser") if isinstance(metadata, dict) else None,
                thumbnail_hash=thumbnail.content_hash if thumbnail is not None else None,
                width=artifact.width if artifact is not None else None,
                height=artifact.height if artifact is not None else None,
                tolerate_count_30d=raw.tolerate_30d_by_id.get(identifier, 0),
                tolerate_count_90d=raw.tolerate_90d_by_id.get(identifier, 0),
                is_quarantined=active_quarantine is not None,
                last_run_at=run.completed_at or run.created_at,
                baseline_change_count=raw.change_count_by_key.get(key, 0),
                recent_drift_avg=raw.recent_drift_by_key.get(key),
                quarantine=(
                    _to_baseline_quarantine_summary(active_quarantine, quarantine_user_infos)
                    if active_quarantine is not None
                    else None
                ),
            )
        )

    totals = contracts.BaselineTotals(
        all_snapshots=raw.totals_all,
        recently_tolerated=raw.totals_recent,
        frequently_tolerated=raw.totals_frequent,
        currently_quarantined=raw.totals_quarantined,
        by_run_type=raw.by_run_type,
    )

    return contracts.BaselineOverview(
        entries=entries,
        totals=totals,
        truncated=raw.truncated,
        generated_at=raw.generated_at,
    )


# --- Run API ---


def list_runs(
    team_id: int,
    review_state: str | None = None,
    repo_id: UUID | None = None,
    pr_number: int | None = None,
    commit_sha: str | None = None,
    branch: str | None = None,
    search: str | None = None,
) -> list[contracts.Run]:
    runs = logic.list_runs_for_team(
        team_id,
        review_state=review_state,
        repo_id=repo_id,
        pr_number=pr_number,
        commit_sha=commit_sha,
        branch=branch,
        search=search,
    )
    return [_to_run(r) for r in runs]


def get_review_state_counts(team_id: int, repo_id: UUID | None = None) -> dict[str, int]:
    return logic.get_review_state_counts(team_id, repo_id=repo_id)


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
        metadata=_sanitize_run_metadata(input.metadata),
        is_partial=input.is_partial,
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


def get_run_snapshots(
    run_id: UUID, team_id: int | None = None, include_quarantined: bool = True
) -> contracts.RunSnapshots:
    if not include_quarantined and team_id is None:
        raise ValueError("team_id is required to exclude quarantined snapshots")
    snapshots = logic.get_run_snapshots(run_id, team_id=team_id)
    if not snapshots:
        return contracts.RunSnapshots(snapshots=[], quarantined_count=0)
    repo_id = snapshots[0].run.repo_id
    run_type = snapshots[0].run.run_type
    quarantined_identifiers = (
        {q.identifier for q in logic.list_quarantined_identifiers(repo_id, team_id, run_type=run_type)}
        if team_id is not None
        else set()
    )
    user_ids = {s.reviewed_by_id for s in snapshots if s.reviewed_by_id}
    user_basic_infos = _fetch_user_basic_infos(user_ids)
    dtos: list[contracts.Snapshot] = []
    quarantined_count = 0
    for s in snapshots:
        dto = _to_snapshot(s, repo_id, user_basic_infos)
        if dto.identifier in quarantined_identifiers:
            quarantined_count += 1
            if not include_quarantined:
                continue
        dtos.append(dto)
    return contracts.RunSnapshots(snapshots=dtos, quarantined_count=quarantined_count)


def get_snapshot_history(repo_id: UUID, identifier: str, run_type: str) -> list[contracts.SnapshotHistoryEntry]:
    entries = logic.get_snapshot_history(repo_id, identifier, run_type)
    return [
        contracts.SnapshotHistoryEntry(
            run_id=e.run_id,
            snapshot_id=e.id,
            result=e.result,
            branch=e.run.branch,
            commit_sha=e.run.commit_sha,
            created_at=e.run.created_at,
            pr_number=e.run.pr_number,
            diff_percentage=e.diff_percentage,
            review_state=e.review_state,
            current_artifact=_to_artifact(e.current_artifact, repo_id) if e.current_artifact else None,
            ssim_score=e.ssim_score,
            change_kind=e.change_kind or "",
            # Read the flag directly instead of round-tripping through the
            # full Pydantic parse — `cluster_summary` isn't on the history
            # entry contract and we'd just be allocating cluster dataclasses
            # to throw away. The default mirrors `DiffMetadata.size_mismatch`.
            size_mismatch=bool((e.diff_metadata or {}).get("size_mismatch", False)),
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


def approve_snapshots(input: contracts.ApproveRunInput, team_id: int | None = None) -> contracts.Run:
    """Mark specific snapshots reviewed (DB only — no baseline commit, no gate change).

    This is the per-snapshot "Accept change" triage action. Shipping the run (committing
    the baseline and greening the gate) happens via finalize_run.
    """
    approved_snapshots = [{"identifier": s.identifier, "new_hash": s.new_hash} for s in input.snapshots]
    run = logic.approve_snapshots(
        run_id=input.run_id,
        user_id=input.user_id,
        approved_snapshots=approved_snapshots,
        team_id=team_id,
    )
    return _to_run(run)


def finalize_run(
    run_id: UUID,
    user_id: int,
    team_id: int | None = None,
    approve_all: bool = False,
    commit_to_github: bool = True,
    add_images_to_comment_on_pr: bool = False,
) -> contracts.FinalizeResult:
    """Finalize a fully-reviewed run: commit the approved baseline and green the gate.

    The single ship action. Commits exactly the snapshots approved in the DB (tolerated
    ones are left alone) and only succeeds once every changed/new snapshot is resolved.
    With ``approve_all=True`` any still-pending snapshot is approved first. The pushed
    baseline commit SHA is surfaced on ``run.metadata["baseline_commit_sha"]``.

    With ``commit_to_github=False`` the server skips the commit and returns the signed
    baseline YAML on ``baseline_content`` instead (for tooling that commits it itself).
    """
    run = logic.finalize_run(
        run_id=run_id,
        user_id=user_id,
        team_id=team_id,
        approve_all=approve_all,
        commit_to_github=commit_to_github,
        add_images_to_comment_on_pr=add_images_to_comment_on_pr,
    )
    baseline_content = "" if commit_to_github else logic.build_signed_baseline(run_id, team_id=team_id)
    return contracts.FinalizeResult(run=_to_run(run), baseline_content=baseline_content)


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


def _to_quarantine_source_run(run) -> contracts.QuarantineSourceRun | None:
    if run is None:
        return None
    return contracts.QuarantineSourceRun(
        id=run.id,
        branch=run.branch,
        commit_sha=run.commit_sha,
        created_at=run.created_at,
        pr_number=run.pr_number,
    )


def _quarantine_common_fields(
    q, user_basic_infos: dict[int, contracts.UserBasicInfo] | None
) -> tuple[contracts.UserBasicInfo | None, contracts.QuarantineSourceRun | None]:
    """Fields shared by both quarantine DTOs. Callers must ensure `q.source_run`
    is preloaded — list/overview use `select_related`, and the create path
    attaches the resolved Run directly — so accessing it never lazy-loads."""
    created_by = (user_basic_infos or {}).get(q.created_by_id) if q.created_by_id else None
    return created_by, _to_quarantine_source_run(q.source_run)


def _to_quarantined_entry(
    q, user_basic_infos: dict[int, contracts.UserBasicInfo] | None = None
) -> contracts.QuarantinedIdentifierEntry:
    created_by, source_run = _quarantine_common_fields(q, user_basic_infos)
    return contracts.QuarantinedIdentifierEntry(
        id=q.id,
        identifier=q.identifier,
        run_type=q.run_type,
        reason=q.reason,
        expires_at=q.expires_at,
        created_at=q.created_at,
        updated_at=q.updated_at,
        created_by=created_by,
        source_run=source_run,
    )


def _to_baseline_quarantine_summary(
    q, user_basic_infos: dict[int, contracts.UserBasicInfo] | None = None
) -> contracts.BaselineQuarantineSummary:
    created_by, source_run = _quarantine_common_fields(q, user_basic_infos)
    return contracts.BaselineQuarantineSummary(
        id=q.id,
        reason=q.reason,
        expires_at=q.expires_at,
        created_at=q.created_at,
        created_by=created_by,
        source_run=source_run,
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
        source_run_id=input.source_run_id,
        user_id=user_id,
        team_id=team_id,
    )
    user_basic_infos = _fetch_user_basic_infos({user_id})
    return _to_quarantined_entry(entry, user_basic_infos)


def unquarantine_identifier(repo_id: UUID, identifier: str, run_type: str, team_id: int) -> None:
    logic.unquarantine_identifier(repo_id=repo_id, identifier=identifier, run_type=run_type, team_id=team_id)


def expire_quarantine_entry(entry_id: UUID, team_id: int) -> None:
    logic.expire_quarantine_entry(entry_id=entry_id, team_id=team_id)
