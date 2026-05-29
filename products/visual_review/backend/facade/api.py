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

from datetime import datetime
from uuid import UUID

from django.contrib.auth import get_user_model

import structlog

from .. import logic
from ..diff_metadata import DiffMetadata
from . import contracts
from .enums import ReviewDecision

User = get_user_model()
logger = structlog.get_logger(__name__)

# Server-owned run.metadata keys — never accept these from client input.
# Allowing clients to set these would let them target arbitrary GitHub
# comments for PATCH, or spoof baseline commit SHAs in the audit trail.
_RESERVED_RUN_METADATA_KEYS = frozenset(
    {
        "github_comment_id",
        "baseline_commit_sha",
        "baseline_healed_from_merge_base",
        "agent_review",
    }
)

# Snapshot metadata is client-supplied (browser, viewport, is_critical, etc.)
# but `agent_review` is server-written from the heuristic/LLM reviewer — a CI
# client must never be able to plant a fake verdict chip in the UI.
_RESERVED_SNAPSHOT_METADATA_KEYS = frozenset({"agent_review"})


def _sanitize_run_metadata(metadata: dict | None) -> dict:
    return _drop_reserved_keys(metadata, _RESERVED_RUN_METADATA_KEYS)


def _sanitize_snapshot_metadata(metadata: dict | None) -> dict:
    return _drop_reserved_keys(metadata, _RESERVED_SNAPSHOT_METADATA_KEYS)


def _drop_reserved_keys(metadata: dict | None, reserved: frozenset[str]) -> dict:
    if not metadata:
        return {}
    if not any(k in reserved for k in metadata):
        return dict(metadata)
    return {k: v for k, v in metadata.items() if k not in reserved}


# Re-export exceptions for callers
RepoNotFoundError = logic.RepoNotFoundError
RunNotFoundError = logic.RunNotFoundError
ArtifactNotFoundError = logic.ArtifactNotFoundError
GitHubIntegrationNotFoundError = logic.GitHubIntegrationNotFoundError
GitHubCommitError = logic.GitHubCommitError
GitHubRateLimitError = logic.GitHubRateLimitError
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


_VALID_VERDICTS = frozenset({"approved", "rejected", "deferred"})


def _parse_agent_verdict(raw: object) -> contracts.AgentVerdict | None:
    """Parse a snapshot-level agent verdict from a metadata JSON blob.

    Returns ``None`` for missing or malformed entries — never raises, so
    a row that never received a verdict (most snapshots), or a stale row
    from an older agent version, doesn't break the snapshots endpoint.
    A malformed verdict (key present but unparseable) is logged at WARN
    so a serialization regression doesn't fail silently.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        logger.warning("visual_review.agent_review.malformed", reason="not_a_dict", raw_type=type(raw).__name__)
        return None
    try:
        verdict = str(raw["verdict"])
        if verdict not in _VALID_VERDICTS:
            logger.warning("visual_review.agent_review.malformed", reason="unknown_verdict", verdict=verdict)
            return None
        return contracts.AgentVerdict(
            verdict=verdict,
            confidence=float(raw["confidence"]),
            reasoning=str(raw["reasoning"]),
            agent=str(raw["agent"]),
            generated_at=datetime.fromisoformat(str(raw["generated_at"])),
        )
    except (KeyError, TypeError, ValueError) as e:
        logger.warning("visual_review.agent_review.malformed", reason="parse_error", error=str(e))
        return None


def _parse_run_agent_review(raw: object) -> contracts.RunAgentReview | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        logger.warning("visual_review.run_agent_review.malformed", reason="not_a_dict", raw_type=type(raw).__name__)
        return None
    try:
        verdict = str(raw["verdict"])
        if verdict not in _VALID_VERDICTS:
            logger.warning("visual_review.run_agent_review.malformed", reason="unknown_verdict", verdict=verdict)
            return None
        return contracts.RunAgentReview(
            verdict=verdict,
            confidence=float(raw["confidence"]),
            summary=str(raw["summary"]),
            agent=str(raw["agent"]),
            generated_at=datetime.fromisoformat(str(raw["generated_at"])),
            snapshot_count=int(raw["snapshot_count"]),
        )
    except (KeyError, TypeError, ValueError) as e:
        logger.warning("visual_review.run_agent_review.malformed", reason="parse_error", error=str(e))
        return None


def _strip_agent_review(metadata: dict | None) -> dict:
    """Return metadata without the agent_review entry.

    The entry is exposed on the typed ``agent_review`` field instead — we
    don't want it appearing twice in the wire response. Returns the
    original dict by reference when the key is absent (the typical case)
    so the hot path through `get_run_snapshots` doesn't pay for a copy
    per snapshot.
    """
    if not metadata:
        return {}
    if "agent_review" not in metadata:
        return metadata
    return {k: v for k, v in metadata.items() if k != "agent_review"}


def _to_snapshot(
    snapshot, repo_id: UUID, user_basic_infos: dict[int, contracts.UserBasicInfo] | None = None
) -> contracts.Snapshot:
    reviewed_by = (user_basic_infos or {}).get(snapshot.reviewed_by_id) if snapshot.reviewed_by_id else None
    cluster_summary, size_mismatch = _parse_diff_metadata(snapshot.diff_metadata)
    raw_metadata = snapshot.metadata or {}
    agent_review = _parse_agent_verdict(raw_metadata.get("agent_review"))
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
        metadata=_strip_agent_review(raw_metadata),
        ssim_score=snapshot.ssim_score,
        change_kind=snapshot.change_kind or "",
        cluster_summary=cluster_summary,
        size_mismatch=size_mismatch,
        agent_review=agent_review,
    )


def _compute_unresolved(run) -> int:
    """Compute unresolved count from prefetched snapshots, or fall back to DB."""
    # Use prefetched snapshots if available (detail view), skip for list views
    if "snapshots" in getattr(run, "_prefetched_objects_cache", {}):
        return sum(1 for s in run.snapshots.all() if logic._is_unresolved(s))
    return 0


def _to_run(run, user_basic_infos: dict[int, contracts.UserBasicInfo] | None = None) -> contracts.Run:
    approved_by = (user_basic_infos or {}).get(run.approved_by_id) if run.approved_by_id else None
    raw_metadata = run.metadata or {}
    agent_review = _parse_run_agent_review(raw_metadata.get("agent_review"))
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
        metadata=_strip_agent_review(raw_metadata),
        agent_review=agent_review,
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
) -> list[contracts.Run]:
    runs = logic.list_runs_for_team(
        team_id,
        review_state=review_state,
        repo_id=repo_id,
        pr_number=pr_number,
        commit_sha=commit_sha,
        branch=branch,
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
            "metadata": _sanitize_snapshot_metadata(s.metadata),
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
            "metadata": _sanitize_snapshot_metadata(s.metadata),
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


def generate_agent_review(run_id: UUID, team_id: int, user) -> contracts.Run:
    """Ask the LLM agent to review the run and return the updated run DTO.

    Advisory only — does not change ``review_state``, does not commit to
    GitHub. Idempotent: re-running overwrites the prior verdict. ``user``
    is threaded through to the LLM client for billing attribution.
    """
    run = logic.generate_agent_review_for_run(run_id=run_id, team_id=team_id, user=user)
    user_ids = {run.approved_by_id} if run.approved_by_id else set()
    return _to_run(run, _fetch_user_basic_infos(user_ids))


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
