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

from collections.abc import Callable
from dataclasses import replace
from datetime import datetime
from uuid import UUID

from django.contrib.auth import get_user_model
from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.egress.github.transport import GitHubRateLimitError
from posthog.helpers.trigram_search import search_match_type_from_instance
from posthog.paging import Page, PageRequest
from posthog.queryset_paging import select_page

from ..diff_metadata import (
    DiffMetadata,
    RowShift as StoredRowShift,
)
from ..logic import (
    approvals,
    artifact_store,
    baseline_overview,
    baseline_record,
    baselines,
    commit_status,
    errors,
    flakiness,
    gating,
    history,
    ledger_adopt,
    ledger_push,
    ledger_repair,
    owners,
    quarantine,
    quarantine_lifts,
    repos,
    review_decisions,
    run_queries,
    runs,
    story_index,
    thumbnails,
    toleration,
)
from . import contracts
from .enums import (
    ActorType,
    DecisionAction,
    DecisionChannel,
    DecisionState,
    QuarantineLiftState,
    ReviewState,
    RunGate,
    RunPurpose,
    RunReviewFilter,
    RunStatus,
    ShiftBandKind,
    SnapshotResult,
)

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
        # The frozen baseline record names the approvals a run counted. A client that could send it
        # would make another pull request's approvals land with its own.
        baseline_record.METADATA_KEY,
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


def _sanitize_snapshot_metadata(metadata: dict | None) -> dict:
    """Drop the review decision history from a client's snapshot metadata. Only `decide` writes it."""
    if not metadata:
        return {}
    return {k: v for k, v in metadata.items() if k != review_decisions.METADATA_KEY}


# Re-export exceptions for callers
RepoNotFoundError = errors.RepoNotFoundError
RunNotFoundError = errors.RunNotFoundError
QuarantineLiftRequestNotFoundError = errors.QuarantineLiftRequestNotFoundError
ArtifactNotFoundError = errors.ArtifactNotFoundError
GitHubIntegrationNotFoundError = errors.GitHubIntegrationNotFoundError
GitHubCommitError = errors.GitHubCommitError
LiftCommitUnknownError = errors.LiftCommitUnknownError
GitHubRateLimitError = GitHubRateLimitError
PRSHAMismatchError = errors.PRSHAMismatchError
StaleRunError = errors.StaleRunError
RunNotFullyResolvedError = errors.RunNotFullyResolvedError
DecisionRefusedError = errors.DecisionRefusedError
SnapshotRejectedError = errors.SnapshotRejectedError
DecidedByPersonError = errors.DecidedByPersonError
BaselineFilePathNotConfiguredError = errors.BaselineFilePathNotConfiguredError
CommitStatusNotPostedError = errors.CommitStatusNotPostedError
BaselineRepairError = errors.BaselineRepairError
BaselineAdoptionError = errors.BaselineAdoptionError


# --- Converters (model -> DTO) ---
#
# These look repetitive when fields align 1:1. The value is having ONE place
# where "internal" becomes "external contract". When models and DTOs drift,
# the mapper absorbs the change instead of it leaking everywhere.


def _to_artifact(artifact, repo_id: UUID) -> contracts.Artifact:
    download_url = artifact_store.get_presigned_download_url(repo_id, artifact.content_hash)
    return contracts.Artifact(
        id=artifact.id,
        content_hash=artifact.content_hash,
        width=artifact.width,
        height=artifact.height,
        download_url=download_url,
    )


def _to_row_shift(parsed: StoredRowShift | None) -> contracts.RowShift | None:
    """Translate the stored row shift into the wire shape.

    Takes the already validated model rather than the raw column, so a caller
    that has parsed `DiffMetadata` does not pay for a second validation. The
    contract carries fewer fields than storage does: the pixel counts behind
    the residual are diagnostics, not something the UI renders.
    """
    if parsed is None:
        return None
    return contracts.RowShift(
        inserted_rows=parsed.inserted_rows,
        deleted_rows=parsed.deleted_rows,
        residual_percentage=parsed.residual_percentage,
        raw_diff_percentage=parsed.raw_diff_percentage,
        bands=[contracts.ShiftBand(y=b.y, rows=b.rows, kind=ShiftBandKind(b.kind)) for b in parsed.bands],
    )


@frozen
class _ParsedDiffMetadata:
    # cluster_summary and row_shift are None for legacy rows and identical-pair
    # rows; size_mismatch is False wherever it was not explicitly recorded.
    cluster_summary: contracts.ClusterSummary | None = None
    size_mismatch: bool = False
    row_shift: contracts.RowShift | None = None


def _parse_diff_metadata(diff_metadata_raw: dict | None) -> _ParsedDiffMetadata:
    """Translate the compact storage shape into the verbose wire shape."""
    if not diff_metadata_raw:
        return _ParsedDiffMetadata()
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
    return _ParsedDiffMetadata(
        cluster_summary=cluster_summary,
        size_mismatch=parsed.size_mismatch,
        row_shift=_to_row_shift(parsed.row_shift),
    )


_DECISION_STATES = {
    DecisionAction.ACCEPT: DecisionState.APPROVED,
    DecisionAction.REJECT: DecisionState.REJECTED,
    DecisionAction.CLEAR: DecisionState.CLEARED,
}


def _user(user_id: int | None, user_basic_infos: dict[int, contracts.UserBasicInfo]) -> contracts.UserBasicInfo | None:
    return user_basic_infos.get(user_id) if user_id is not None else None


def _to_snapshot_decision(
    decision: review_decisions.Decision, run_commit_sha: str, user_basic_infos: dict[int, contracts.UserBasicInfo]
) -> contracts.SnapshotDecision:
    return contracts.SnapshotDecision(
        state=_DECISION_STATES[decision.action],
        by=_user(decision.by_id, user_basic_infos),
        via=decision.via,
        at=decision.at,
        reason=decision.reason,
        run_id=decision.run_id,
        commit_sha=decision.commit_sha,
        from_earlier_commit=decision.commit_sha != run_commit_sha,
        seq=decision.seq,
    )


def _to_earlier_decision(
    decision: review_decisions.Decision,
    key: review_decisions.DecisionKey,
    user_basic_infos: dict[int, contracts.UserBasicInfo],
) -> contracts.EarlierSnapshotDecision:
    return contracts.EarlierSnapshotDecision(
        state=_DECISION_STATES[decision.action],
        by=_user(decision.by_id, user_basic_infos),
        via=decision.via,
        at=decision.at,
        reason=decision.reason,
        commit_sha=decision.commit_sha,
        changed=review_decisions.changed_side(decision, key),
    )


@frozen
class _SnapshotDecisions:
    """The decisions that count on one run, for the snapshots of that run a read returns."""

    decisions: review_decisions.PullRequestDecisions
    run_commit_sha: str

    def effective(self, snapshot) -> review_decisions.EffectiveDecision:
        return self.decisions.effective(
            review_decisions.key_of(snapshot.identifier, snapshot.baseline_hash, snapshot.current_hash)
        )


def _decision_user_ids(snapshots, decisions: _SnapshotDecisions | None) -> set[int]:
    user_ids = {s.reviewed_by_id for s in snapshots if s.reviewed_by_id}
    if decisions is None:
        return user_ids
    for snapshot in snapshots:
        effective = decisions.effective(snapshot)
        for decision in (effective.decision, effective.earlier):
            if decision is not None and decision.by_id is not None:
                user_ids.add(decision.by_id)
    return user_ids


def _to_snapshot(
    snapshot,
    repo_id: UUID,
    user_basic_infos: dict[int, contracts.UserBasicInfo] | None = None,
    decisions: _SnapshotDecisions | None = None,
) -> contracts.Snapshot:
    """`decisions` makes `review_state` the effective state on the run, and adds the decision fields."""
    infos = user_basic_infos or {}
    reviewed_by = infos.get(snapshot.reviewed_by_id) if snapshot.reviewed_by_id else None
    diff_meta = _parse_diff_metadata(snapshot.diff_metadata)
    review_state = snapshot.review_state
    reviewed_at = snapshot.reviewed_at
    approved_hash = snapshot.approved_hash
    decision: contracts.SnapshotDecision | None = None
    earlier: contracts.EarlierSnapshotDecision | None = None
    if decisions is not None:
        effective = decisions.effective(snapshot)
        review_state = review_decisions.effective_review_state(snapshot.review_state, effective)
        # The older review fields describe the same decision as `review_state`, not what the row last stored.
        if effective.decision is not None:
            decision = _to_snapshot_decision(effective.decision, decisions.run_commit_sha, infos)
            reviewed_by = _user(effective.decision.by_id, infos)
            reviewed_at = effective.decision.at
            approved_hash = (effective.decision.key.new_hash or "") if effective.accepted else ""
        elif review_state == ReviewState.PENDING:
            reviewed_by, reviewed_at, approved_hash = None, None, ""
        if effective.earlier is not None:
            key = review_decisions.key_of(snapshot.identifier, snapshot.baseline_hash, snapshot.current_hash)
            earlier = _to_earlier_decision(effective.earlier, key, infos)
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
        review_state=review_state,
        reviewed_at=reviewed_at,
        approved_hash=approved_hash,
        tolerated_hash_id=snapshot.tolerated_hash_match_id,
        is_quarantined=snapshot.is_quarantined,
        reviewed_by=reviewed_by,
        metadata=snapshot.metadata or {},
        ssim_score=snapshot.ssim_score,
        change_kind=snapshot.change_kind or "",
        cluster_summary=diff_meta.cluster_summary,
        size_mismatch=diff_meta.size_mismatch,
        row_shift=diff_meta.row_shift,
        decision=decision,
        earlier_decision=earlier,
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
        return sum(1 for s in run.snapshots.all() if gating._is_unresolved(s))
    return 0


def _to_progress(progress: review_decisions.RunProgress) -> contracts.RunProgress:
    return contracts.RunProgress(
        total=progress.total,
        approved=progress.approved,
        approved_on_earlier_commits=progress.approved_on_earlier_commits,
        approved_via_mcp=progress.approved_via_mcp,
        rejected=progress.rejected,
        needs_review=progress.needs_review,
        tolerated=progress.tolerated,
    )


def _to_head_run(run) -> contracts.HeadRun:
    return contracts.HeadRun(id=run.id, commit_sha=run.commit_sha, status=run.status, approved=run.approved)


def _can_finalize(run, head, review: review_decisions.RunReview) -> bool:
    """Whether a finalize without `approve_all` would pass now.

    Finalize accepts a removal nobody rejected by itself, so an undecided removal does not hold it
    back, although it counts in `needs_review` and keeps the gate open until then.
    """
    open_changes = [
        snapshot
        for snapshot in review.with_standing(review_decisions.Standing.NEEDS_REVIEW)
        if snapshot.result != SnapshotResult.REMOVED
    ]
    return (
        run.id == head.id
        and run.purpose == RunPurpose.REVIEW
        and run.status == RunStatus.COMPLETED
        and not run.approved
        and review.rejected_count == 0
        and not open_changes
    )


def _to_run(
    run,
    user_basic_infos: dict[int, contracts.UserBasicInfo] | None = None,
    unresolved: int | None = None,
    stale_approval_count: int = 0,
    progress: review_decisions.RunProgress | None = None,
    head=None,
    can_finalize: bool = False,
) -> contracts.Run:
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
            unresolved=_compute_unresolved(run) if unresolved is None else unresolved,
            tolerated_matched=run.tolerated_match_count,
        ),
        error_message=run.error_message or None,
        created_at=run.created_at,
        completed_at=run.completed_at,
        purpose=run.purpose,
        is_stale=run_queries.is_run_stale(run),
        superseded_by_id=run.superseded_by_id,
        approved_by=approved_by,
        metadata=run.metadata or {},
        # Present only when the queryset came from a trigram search (annotation absent otherwise).
        search_match_type=search_match_type_from_instance(run),
        gate=RunGate(run.gate),
        stale_approval_count=stale_approval_count,
        progress=_to_progress(progress) if progress is not None else None,
        head_run=_to_head_run(head) if head is not None else None,
        can_finalize=can_finalize,
    )


def _to_repo(repo) -> contracts.Repo:
    return contracts.Repo(
        id=repo.id,
        team_id=repo.team_id,
        repo_external_id=repo.repo_external_id,
        repo_full_name=repo.repo_full_name,
        baseline_file_paths=repo.baseline_file_paths,
        enable_pr_comments=repo.enable_pr_comments,
        debt_digest_enabled=repo.debt_digest_enabled,
        auto_quarantine_mode=repo.auto_quarantine_mode,
        created_at=repo.created_at,
    )


# --- Repo API ---


def get_repo(repo_id: UUID, team_id: int) -> contracts.Repo:
    repo = repos.get_repo(repo_id, team_id)
    return _to_repo(repo)


def repair_baseline_ledger(
    repo_id: UUID,
    team_id: int,
    run_type: str,
    *,
    apply: bool,
    on_progress: Callable[[int, int], None] | None = None,
) -> contracts.BaselineLedgerRepair:
    """Plan, or with `apply` write, the entries that make the baseline ledger equal the baseline file. Shadow mode only.

    `on_progress` gets the number of ledger positions read so far and the number to read.
    """
    repo = repos.get_repo(repo_id, team_id)
    if apply:
        return ledger_repair.apply_repair(repo, run_type, on_progress)
    return ledger_repair.plan_repair(repo, run_type, on_progress)


def plan_ledger_adoption(
    repo_id: UUID, team_id: int, run_type: str, run_id: UUID, identifiers: list[str]
) -> contracts.BaselineLedgerAdoption:
    """The entries that would set the ledger to what a full default-branch run rendered, without writing them.

    Ledger mode only. Covers only the named identifiers.
    """
    repo = repos.get_repo(repo_id, team_id)
    return ledger_adopt.plan_adoption(repo, run_type, run_id, identifiers)


def adopt_ledger_renders(
    repo_id: UUID, team_id: int, run_type: str, run_id: UUID, identifiers: list[str]
) -> contracts.BaselineLedgerAdoption:
    """Write the entries that set the ledger to what a full default-branch run rendered. Ledger mode only."""
    repo = repos.get_repo(repo_id, team_id)
    return ledger_adopt.adopt_renders(repo, run_type, run_id, identifiers)


def list_repos(team_id: int, page: PageRequest) -> Page[contracts.Repo]:
    return select_page(repos.list_repos_for_team(team_id), page).map(_to_repo)


def create_repo(team_id: int, repo_external_id: int, repo_full_name: str) -> contracts.Repo:
    repo = repos.create_repo(team_id=team_id, repo_external_id=repo_external_id, repo_full_name=repo_full_name)
    return _to_repo(repo)


def update_repo(input: contracts.UpdateRepoInput, team_id: int) -> contracts.Repo:
    repo = repos.update_repo(input, team_id=team_id)
    return _to_repo(repo)


def get_thumbnail_hash_for_identifier(repo_id: UUID, identifier: str, run_type: str | None = None) -> str | None:
    """Resolve a snapshot identifier to the content hash of its thumbnail, if any.

    `run_type` narrows to one, for callers that list several side by side.
    """
    return thumbnails.get_thumbnail_hash_for_identifier(repo_id, identifier, run_type)


def read_thumbnail_bytes(repo_id: UUID, content_hash: str) -> bytes | None:
    """Read the raw bytes for a thumbnail artifact from storage."""
    return thumbnails.read_thumbnail_bytes(repo_id, content_hash)


def get_baselines_overview(repo_id: UUID) -> contracts.BaselineOverview:
    """Universe of identifiers with a current baseline, plus aggregates.

    Backs the snapshots overview page. See `baseline_overview.get_baselines_overview` for
    query shape and performance notes.
    """
    raw = baseline_overview.get_baselines_overview(repo_id)

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
        # Keyed per identity because the same identifier in different run types
        # is a different baseline.
        key = run_queries.SnapshotKey(run_type=run.run_type, identifier=identifier)
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
                active_variants_current_baseline=raw.active_variants_by_key.get(key, 0),
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
        variant_pileups=raw.totals_variant_pileups,
        by_run_type=raw.by_run_type,
    )

    return contracts.BaselineOverview(
        entries=entries,
        totals=totals,
        truncated=raw.truncated,
        generated_at=raw.generated_at,
    )


def get_toleration_pileups(
    repo_id: UUID,
    *,
    window_days: int = contracts.TOLERATION_PILEUP_WINDOW_DAYS,
    min_tolerations: int = contracts.VARIANT_PILEUP_MIN,
    min_automatic_tolerations: int | None = None,
    include_quarantined: bool = True,
    run_type: str | None = None,
    limit: int = 100,
) -> contracts.TolerationPileups:
    """Snapshot identities that keep getting tolerated, biggest manual pile first.

    Backs the pile-ups endpoint, which agents read. The defaults are the debt digest's rule, except
    that quarantined identities stay in the list and are marked, so a reader sees open and muted
    piles alike.
    """
    now = timezone.now()
    quarantined_keys = quarantine.active_quarantine_keys(repo_id, now=now)
    pileups = toleration.list_toleration_pileups(
        repo_id,
        now=now,
        window_days=window_days,
        min_intentional=min_tolerations,
        min_automatic=min_automatic_tolerations,
    )
    matching = [
        (key, counts)
        for key, counts in pileups
        if (include_quarantined or key not in quarantined_keys) and (run_type is None or key.run_type == run_type)
    ]
    return contracts.TolerationPileups(
        entries=[
            contracts.TolerationPileupEntry(
                identifier=key.identifier,
                run_type=key.run_type,
                intentional_count=counts.intentional,
                automatic_count=counts.automatic,
                is_quarantined=key in quarantined_keys,
            )
            for key, counts in matching[:limit]
        ],
        window_days=window_days,
        min_tolerations=min_tolerations,
        min_automatic_tolerations=min_automatic_tolerations,
        total=len(matching),
        truncated=len(matching) > limit,
        generated_at=now,
    )


def get_flakiness_overview(repo_id: UUID, team_id: int) -> contracts.FlakinessOverview:
    """Snapshot identities carrying rendering instability or an open quarantine.

    Backs the flakiness page. See `flakiness.get_flakiness_overview` for the
    scoping rule and query shape.
    """
    raw = flakiness.get_flakiness_overview(repo_id)
    owner_team_by_key = owners.owner_teams(
        repos.get_repo(repo_id, team_id), [flakiness.snapshot_key(row) for row in raw.rows], raw.newest_run_by_type
    )

    quarantine_user_ids = {
        row.quarantine.created_by_id for row in raw.rows if row.quarantine and row.quarantine.created_by_id
    }
    quarantine_user_infos = _fetch_user_basic_infos(quarantine_user_ids)

    entries: list[contracts.FlakinessEntry] = []
    for row in raw.rows:
        snapshot = raw.snapshots_by_key.get(flakiness.snapshot_key(row))
        artifact = snapshot.current_artifact if snapshot is not None else None
        thumbnail = artifact.thumbnail if artifact is not None else None
        metadata = (snapshot.metadata or {}) if snapshot is not None else {}
        entries.append(
            contracts.FlakinessEntry(
                identifier=row.identifier,
                run_type=row.run_type,
                browser=metadata.get("browser") if isinstance(metadata, dict) else None,
                thumbnail_hash=thumbnail.content_hash if thumbnail is not None else None,
                width=artifact.width if artifact is not None else None,
                height=artifact.height if artifact is not None else None,
                variant_count=row.variant_count,
                hard_count=row.hard_count,
                soft_count=row.soft_count,
                window_runs=row.window_runs,
                hard_rate=row.hard_rate,
                soft_rate=row.soft_rate,
                last_flaked_at=row.last_flaked_at,
                avg_diff_percentage=row.avg_diff_percentage,
                worst_soft_diff_percentage=row.worst_soft_diff_percentage,
                headroom=row.headroom,
                baseline_age_days=_days_since(row.baseline_moved_at, raw.generated_at),
                daily_hard_counts=row.daily_hard_counts,
                daily_soft_counts=row.daily_soft_counts,
                baseline_moved_day_index=_baseline_moved_day_index(row.baseline_moved_at, raw.generated_at),
                flakiness_state=row.state,
                is_quarantined=row.quarantine is not None,
                needs_decision=row.needs_decision,
                quarantine=(
                    _to_baseline_quarantine_summary(row.quarantine, quarantine_user_infos)
                    if row.quarantine is not None
                    else None
                ),
                owner_team=owner_team_by_key.get(flakiness.snapshot_key(row)),
            )
        )

    totals = contracts.FlakinessTotals(
        listed=len(entries),
        tracked=raw.tracked_total,
        broken=raw.totals_broken,
        unstable=raw.totals_unstable,
        at_risk=raw.totals_at_risk,
        clean=raw.totals_clean,
        quarantined=raw.totals_quarantined,
        needs_decision=raw.totals_needs_decision,
        by_run_type=raw.by_run_type,
    )

    return contracts.FlakinessOverview(
        entries=entries,
        totals=totals,
        truncated=raw.truncated,
        generated_at=raw.generated_at,
    )


def _days_since(moment: datetime | None, now: datetime) -> int | None:
    return None if moment is None else max((now - moment).days, 0)


def _baseline_moved_day_index(moved_at: datetime | None, now: datetime) -> int | None:
    """Position of the baseline move inside the activity strip.

    None when the baseline moved before the strip window opened, which is the
    common case, so the frontend draws no divider.
    """
    days_ago = _days_since(moved_at, now)
    if days_ago is None or days_ago >= contracts.FLAKINESS_WINDOW_DAYS:
        return None
    return contracts.FLAKINESS_WINDOW_DAYS - 1 - days_ago


# --- Run API ---


def list_runs(
    team_id: int,
    review_state: RunReviewFilter | None = None,
    repo_id: UUID | None = None,
    pr_number: int | None = None,
    commit_sha: str | None = None,
    branch: str | None = None,
    search: str | None = None,
    *,
    page: PageRequest,
) -> Page[contracts.Run]:
    runs = run_queries.list_runs_for_team(
        team_id,
        review_state=review_state,
        repo_id=repo_id,
        pr_number=pr_number,
        commit_sha=commit_sha,
        branch=branch,
        search=search,
    )
    return select_page(runs, page).map(_to_run)


def get_review_state_counts(team_id: int, repo_id: UUID | None = None) -> dict[str, int]:
    return run_queries.get_review_state_counts(team_id, repo_id=repo_id)


def create_run(input: contracts.CreateRunInput, team_id: int) -> contracts.CreateRunResult:
    # Sanitize metadata at the facade boundary before handing the DTO to logic.
    input = replace(
        input,
        metadata=_sanitize_run_metadata(input.metadata),
        snapshots=[replace(s, metadata=_sanitize_snapshot_metadata(s.metadata)) for s in input.snapshots],
    )
    run, uploads = runs.create_run(input, team_id=team_id)

    upload_targets = [
        contracts.UploadTarget(
            content_hash=u["content_hash"],
            url=u["url"],
            fields=u["fields"],
        )
        for u in uploads
    ]

    return contracts.CreateRunResult(run_id=run.id, uploads=upload_targets)


def report_no_run_needed(input: contracts.NoRunNeededInput, team_id: int) -> contracts.NoRunNeededResult:
    """Post a passing commit status for a commit that needs no visual run, unless a run owns the status."""
    repo = repos.get_repo(input.repo_id, team_id)
    outcome = commit_status.report_no_run_needed(repo, input)
    return contracts.NoRunNeededResult(
        outcome=outcome, detail=commit_status.no_run_needed_detail(outcome, input.run_type)
    )


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

    added, uploads = runs.add_snapshots_to_run(
        run_id=run_id,
        team_id=team_id,
        snapshots=snapshots,
        baseline_hashes=input.baseline_hashes,
    )

    upload_targets = [
        contracts.UploadTarget(content_hash=u["content_hash"], url=u["url"], fields=u["fields"]) for u in uploads
    ]

    story_index_upload = None
    if input.story_index_hash:
        upload = story_index.register_story_index(run_id, team_id, input.story_index_hash)
        if upload is not None:
            story_index_upload = contracts.UploadTarget(
                content_hash=input.story_index_hash, url=upload.url, fields=upload.fields
            )

    return contracts.AddSnapshotsResult(added=added, uploads=upload_targets, story_index_upload=story_index_upload)


def get_run(run_id: UUID, team_id: int | None = None) -> contracts.Run:
    run = run_queries.get_run(run_id, team_id=team_id)
    user_ids = {run.approved_by_id} if run.approved_by_id else set()
    user_basic_infos = _fetch_user_basic_infos(user_ids)
    review = review_decisions.review_run(run)
    head = review_decisions.head_run(run)
    return _to_run(
        run,
        user_basic_infos,
        unresolved=(
            review.needs_review_count + review.rejected_count
            if review_decisions.decides_by_pull_request(run)
            else gating.count_unresolved(run)
        ),
        stale_approval_count=commit_status.stale_approval_count(run),
        progress=review.progress(),
        head=head,
        can_finalize=_can_finalize(run, head, review),
    )


def get_run_scope(run_id: UUID, team_id: int) -> contracts.RunScope:
    """The repo and run type a run belongs to, for endpoints that only need to know where to look."""
    run = run_queries.get_run(run_id, team_id=team_id)
    return contracts.RunScope(repo_id=run.repo_id, run_type=run.run_type)


def _identifiers_in_review_state(snapshots, decisions: _SnapshotDecisions, review_state: str) -> list[str]:
    """The identifiers among `snapshots` whose effective review state is `review_state`."""
    return [
        identifier
        for identifier, baseline_hash, current_hash, row_state in snapshots.values_list(
            "identifier", "baseline_hash", "current_hash", "review_state"
        )
        if review_decisions.effective_review_state(
            row_state,
            decisions.decisions.effective(review_decisions.key_of(identifier, baseline_hash, current_hash)),
        )
        == review_state
    ]


def get_run_snapshots(
    run_id: UUID,
    team_id: int | None = None,
    include_quarantined: bool = True,
    exclude_unchanged: bool = False,
    snapshot_id: UUID | None = None,
    quarantined_only: bool = False,
    limit: int | None = None,
    offset: int = 0,
    review_state: str | None = None,
) -> contracts.RunSnapshots:
    """One page of a run's snapshots. `limit=None` returns every match from `offset` on.

    Filtering and paging stay in SQL, and only the page becomes DTOs, because each DTO
    signs a download URL per artifact and a large run holds thousands of rows.
    `quarantined_only` keeps only the quarantined snapshots and overrides `include_quarantined`.
    A rejected snapshot is listed even when quarantined or unchanged snapshots are left out, because
    it still blocks finalize. `review_state` filters on the effective state, which can come from a decision
    made on another run of the pull request.
    """
    if (quarantined_only or not include_quarantined) and team_id is None:
        raise ValueError("team_id is required to filter snapshots by quarantine")
    run = run_queries.get_run(run_id, team_id=team_id)
    decisions = _SnapshotDecisions(
        decisions=review_decisions.pull_request_decisions(run), run_commit_sha=run.commit_sha
    )
    # Only ledger mode keeps a decision history. Elsewhere the decisions above are read back from
    # the rows' own review state, which records no channel, so a read shows no decision.
    shown_decisions = decisions if review_decisions.decides_by_pull_request(run) else None
    rejected: set[str] = set()
    if shown_decisions is not None and (exclude_unchanged or not include_quarantined):
        rejected = {
            snapshot.identifier
            for snapshot in review_decisions.review_run(run, decisions.decisions).with_standing(
                review_decisions.Standing.REJECTED
            )
        }
    # A tolerated pair is unchanged, and still blocks the run when someone rejected it.
    snapshots = run_queries.run_snapshots(
        run, exclude_unchanged=exclude_unchanged, snapshot_id=snapshot_id, unchanged_kept=frozenset(rejected)
    )

    quarantined_count = 0
    if team_id is not None:
        quarantined = quarantine.active_quarantined_identifiers(run.repo_id, team_id, run.run_type, using=snapshots.db)
        quarantined_count = snapshots.filter(identifier__in=quarantined).count()
        if quarantined_only:
            snapshots = snapshots.filter(identifier__in=quarantined)
        elif not include_quarantined:
            snapshots = snapshots.exclude(identifier__in=set(quarantined) - rejected)
    if review_state is not None:
        snapshots = snapshots.filter(identifier__in=_identifiers_in_review_state(snapshots, decisions, review_state))

    total_count = snapshots.count()
    page = list(snapshots[offset : offset + limit if limit is not None else None])
    user_basic_infos = _fetch_decider_infos(_decision_user_ids(page, shown_decisions), run.team_id)
    return contracts.RunSnapshots(
        snapshots=[_to_snapshot(s, run.repo_id, user_basic_infos, shown_decisions) for s in page],
        quarantined_count=quarantined_count,
        total_count=total_count,
    )


def _to_history_entry(entry, repo_id: UUID) -> contracts.SnapshotHistoryEntry:
    # Validate the stored column once and read both fields off it. The history
    # contract has no `cluster_summary`, so the parse stops at the pydantic
    # model rather than building the cluster dataclasses that would be thrown
    # away. Defaults mirror `DiffMetadata`.
    stored = DiffMetadata.model_validate(entry.diff_metadata or {})
    return contracts.SnapshotHistoryEntry(
        run_id=entry.run_id,
        snapshot_id=entry.id,
        result=entry.result,
        branch=entry.run.branch,
        commit_sha=entry.run.commit_sha,
        created_at=entry.run.created_at,
        pr_number=entry.run.pr_number,
        diff_percentage=entry.diff_percentage,
        review_state=entry.review_state,
        current_artifact=_to_artifact(entry.current_artifact, repo_id) if entry.current_artifact else None,
        ssim_score=entry.ssim_score,
        change_kind=entry.change_kind or "",
        size_mismatch=stored.size_mismatch,
        row_shift=_to_row_shift(stored.row_shift),
    )


def get_snapshot_history(repo_id: UUID, identifier: str, run_type: str) -> list[contracts.SnapshotHistoryEntry]:
    entries = history.get_snapshot_history(repo_id, identifier, run_type)
    return [_to_history_entry(entry, repo_id) for entry in entries]


def mark_snapshot_as_tolerated(
    run_id: UUID, snapshot_id: UUID, user_id: int, team_id: int, actor: ActorType = ActorType.HUMAN
) -> contracts.Snapshot:
    snapshot = toleration.mark_snapshot_as_tolerated(run_id, snapshot_id, user_id, team_id, actor=actor)
    return _to_snapshot(snapshot, snapshot.run.repo_id)


def get_tolerated_hashes(repo_id: UUID, identifier: str) -> list[contracts.ToleratedHashEntry]:
    entries = toleration.get_tolerated_hashes_for_identifier(repo_id, identifier)
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


def complete_run(run_id: UUID, team_id: int | None = None, check_run_id: str | None = None) -> contracts.Run:
    """
    Complete a run: detect removals, verify uploads, trigger diff processing.
    """
    if team_id is not None:
        run_queries.get_run(run_id, team_id=team_id)  # validates ownership
    run = runs.complete_run(run_id)
    # After `complete_run`, whose baseline healing saves a whole metadata dict it may have read stale.
    if check_run_id is not None:
        runs.record_completing_job(run_id, check_run_id)
    # A re-run of the completing CI job lands here on a completed run, and the CLI gates on this
    # number, so it must be the commit status verdict and not the unprefetched default of 0.
    return _to_run(run, unresolved=gating.count_gating(run))


def recompute_run(run_id: UUID, team_id: int | None = None) -> contracts.RecomputeResult:
    result = runs.recompute_run(run_id, team_id=team_id)
    run = run_queries.get_run_with_snapshots(run_id, team_id=team_id)
    return contracts.RecomputeResult(
        run=_to_run(run),
        counts_changed=result["counts_changed"],
        unresolved=result["unresolved"],
        ci_rerun_triggered=result["ci_rerun_triggered"],
        ci_rerun_error=result["ci_rerun_error"],
    )


def _to_decision_result(outcome: approvals.DecisionOutcome) -> contracts.DecisionResult:
    return contracts.DecisionResult(
        run=_to_run(outcome.run),
        head_run=_to_head_run(outcome.head),
        progress=_to_progress(outcome.head_review.progress()),
        already_decided=list(outcome.already_decided),
    )


def approve_snapshots(
    input: contracts.ApproveRunInput, team_id: int, via: DecisionChannel = DecisionChannel.WEB
) -> contracts.DecisionResult:
    """Accept snapshots (DB only — no baseline commit, no gate pass).

    This is the per-snapshot "Accept change" triage action. Shipping the run (recording or
    committing the baseline and passing the gate) happens via finalize_run.
    """
    outcome = approvals.decide(
        input.run_id,
        input.user_id,
        DecisionAction.ACCEPT,
        [
            approvals.DecisionRequest(identifier=s.identifier, new_hash=s.new_hash, old_hash=s.old_hash)
            for s in input.snapshots
        ],
        via=via,
        team_id=team_id,
        expected_seq=input.expected_seq,
        override_rejection=input.override_rejection,
    )
    return _to_decision_result(outcome)


def reject_snapshots(
    input: contracts.RejectRunInput, team_id: int, via: DecisionChannel = DecisionChannel.WEB
) -> contracts.DecisionResult:
    """Reject snapshots with a reason. A rejection blocks finalize until the picture changes or it is undone."""
    outcome = approvals.decide(
        input.run_id,
        input.user_id,
        DecisionAction.REJECT,
        [
            approvals.DecisionRequest(
                identifier=s.identifier, new_hash=s.new_hash, old_hash=s.old_hash, reason=s.reason
            )
            for s in input.snapshots
        ],
        via=via,
        team_id=team_id,
        expected_seq=input.expected_seq,
    )
    return _to_decision_result(outcome)


def clear_snapshot_decisions(
    input: contracts.ClearRunInput, team_id: int, via: DecisionChannel = DecisionChannel.WEB
) -> contracts.DecisionResult:
    """Undo the accept or reject of snapshots, so they need review again."""
    outcome = approvals.decide(
        input.run_id,
        input.user_id,
        DecisionAction.CLEAR,
        [approvals.DecisionRequest(identifier=identifier) for identifier in input.identifiers],
        via=via,
        team_id=team_id,
        expected_seq=input.expected_seq,
        override_rejection=input.override_rejection,
    )
    return _to_decision_result(outcome)


def not_fully_resolved_detail(error: errors.RunNotFullyResolvedError, team_id: int) -> contracts.NotFullyResolvedDetail:
    user_basic_infos = _fetch_decider_infos({r.by_id for r in error.rejected if r.by_id is not None}, team_id)
    return contracts.NotFullyResolvedDetail(
        rejected=[
            contracts.RejectedSnapshotDetail(
                identifier=r.identifier, by=_user(r.by_id, user_basic_infos), reason=r.reason
            )
            for r in error.rejected
        ],
        needs_review=error.needs_review,
    )


def finalize_run(
    run_id: UUID,
    user_id: int,
    team_id: int | None = None,
    approve_all: bool = False,
    commit_to_github: bool = True,
    add_images_to_comment_on_pr: bool = False,
    via: DecisionChannel = DecisionChannel.WEB,
) -> contracts.FinalizeResult:
    """Finalize a fully-reviewed run: commit the approved baseline and green the gate.

    The single ship action. Commits exactly the snapshots approved in the DB (tolerated
    ones are left alone) and only succeeds once every changed/new snapshot is resolved.
    With ``approve_all=True`` any still-pending snapshot is approved first. The pushed
    baseline commit SHA is surfaced on ``run.metadata["baseline_commit_sha"]``.

    With ``commit_to_github=False`` the server skips the commit and returns the signed
    baseline YAML on ``baseline_content`` instead (for tooling that commits it itself).
    """
    run = approvals.finalize_run(
        run_id=run_id,
        user_id=user_id,
        team_id=team_id,
        approve_all=approve_all,
        commit_to_github=commit_to_github,
        add_images_to_comment_on_pr=add_images_to_comment_on_pr,
        via=via,
    )
    baseline_content = "" if commit_to_github else baselines.build_signed_baseline(run_id, team_id=team_id)
    review = review_decisions.review_run(run)
    groups = review_decisions.approver_groups(review)
    user_basic_infos = _fetch_decider_infos({group.by_id for group in groups if group.by_id is not None}, run.team_id)
    return contracts.FinalizeResult(
        run=_to_run(run),
        baseline_content=baseline_content,
        progress=_to_progress(review.progress()),
        approvers=[
            contracts.FinalizeApprover(
                user=_user(group.by_id, user_basic_infos),
                via=group.via,
                count=group.count,
                commit_shas=list(group.commit_shas),
            )
            for group in groups
        ],
    )


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


def _fetch_decider_infos(user_ids: set[int], team_id: int) -> dict[int, contracts.UserBasicInfo]:
    """The users that decisions name, resolved only within the team's organization.

    A decision entry stored before uploads dropped the history key can name any user ID, and its
    name and email must not reach a reader outside that user's organization.
    """
    if not user_ids:
        return {}
    return _fetch_user_basic_infos(user_ids & review_decisions.organization_member_ids(team_id))


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
        source=q.source,
        expires_at=q.expires_at,
        created_at=q.created_at,
        updated_at=q.updated_at,
        created_by=created_by,
        source_run=source_run,
        lift_reason=q.lift_reason,
    )


def _to_baseline_quarantine_summary(
    q, user_basic_infos: dict[int, contracts.UserBasicInfo] | None = None
) -> contracts.BaselineQuarantineSummary:
    created_by, source_run = _quarantine_common_fields(q, user_basic_infos)
    return contracts.BaselineQuarantineSummary(
        id=q.id,
        reason=q.reason,
        source=q.source,
        expires_at=q.expires_at,
        created_at=q.created_at,
        created_by=created_by,
        source_run=source_run,
    )


def list_quarantined(
    repo_id: UUID,
    team_id: int,
    identifier: str | None = None,
    run_type: str | None = None,
    *,
    page: PageRequest,
) -> Page[contracts.QuarantinedIdentifierEntry]:
    entries = select_page(
        quarantine.list_quarantined_identifiers(repo_id, team_id, identifier=identifier, run_type=run_type), page
    )
    user_ids = {e.created_by_id for e in entries.results if e.created_by_id}
    user_basic_infos = _fetch_user_basic_infos(user_ids)
    return entries.map(lambda entry: _to_quarantined_entry(entry, user_basic_infos))


def quarantine_identifier(
    repo_id: UUID,
    run_type: str,
    input: contracts.QuarantineInput,
    user_id: int,
    team_id: int,
    source: ActorType = ActorType.HUMAN,
) -> contracts.QuarantinedIdentifierEntry:
    entry = quarantine.quarantine_identifier(
        repo_id=repo_id,
        identifier=input.identifier,
        run_type=run_type,
        reason=input.reason,
        expires_at=input.expires_at,
        source_run_id=input.source_run_id,
        source=source,
        user_id=user_id,
        team_id=team_id,
        notify_owners=input.notify_owners,
    )
    user_basic_infos = _fetch_user_basic_infos({user_id})
    return _to_quarantined_entry(entry, user_basic_infos)


def unquarantine_identifier(repo_id: UUID, identifier: str, run_type: str, team_id: int) -> None:
    quarantine.unquarantine_identifier(repo_id=repo_id, identifier=identifier, run_type=run_type, team_id=team_id)


def expire_quarantine_entry(entry_id: UUID, team_id: int) -> None:
    quarantine.expire_quarantine_entry(entry_id=entry_id, team_id=team_id)


# --- Quarantine lift on merge ---


def _to_quarantine_lift_entry(
    request, user_basic_infos: dict[int, contracts.UserBasicInfo] | None = None
) -> contracts.QuarantineLiftEntry:
    requested_by = (user_basic_infos or {}).get(request.requested_by_id) if request.requested_by_id else None
    return contracts.QuarantineLiftEntry(
        id=request.id,
        quarantine_id=request.quarantine_id,
        identifier=request.identifier,
        run_type=request.run_type,
        pr_number=request.pr_number,
        expected_hash=request.expected_hash,
        state=QuarantineLiftState(request.state),
        detail=request.detail,
        source=request.source,
        created_at=request.created_at,
        updated_at=request.updated_at,
        resolved_at=request.resolved_at,
        source_run_id=request.source_run_id,
        requested_by=requested_by,
        merge_commit_sha=request.merge_commit_sha,
        lifted_at_sha=request.lifted_at_sha,
    )


def request_quarantine_lift_on_merge(
    run_id: UUID,
    input: contracts.LiftOnMergeInput,
    user_id: int,
    team_id: int,
    source: ActorType = ActorType.HUMAN,
) -> contracts.QuarantineLiftEntry:
    """Lift a quarantined snapshot's quarantine once the run's pull request merges.

    Raises RunNotFoundError for a missing run or snapshot, StaleRunError for a superseded run,
    and ValueError with a reviewer-readable message for any other refusal.
    """
    request = quarantine_lifts.request_lift_on_merge(
        run_id, input.identifier, team_id=team_id, user_id=user_id, source=source
    )
    return _to_quarantine_lift_entry(request, _fetch_user_basic_infos({user_id}))


def list_quarantine_lifts_for_run(run_id: UUID, team_id: int) -> list[contracts.QuarantineLiftEntry]:
    """Every lift request made for the run's pull request, newest first. Empty for a run without one."""
    run = run_queries.get_run(run_id, team_id=team_id)
    if run.pr_number is None:
        return []
    requests = quarantine_lifts.list_lift_requests_for_pr(run.repo_id, team_id, run.pr_number)
    user_basic_infos = _fetch_user_basic_infos({r.requested_by_id for r in requests if r.requested_by_id})
    return [_to_quarantine_lift_entry(r, user_basic_infos) for r in requests]


def cancel_quarantine_lift(run_id: UUID, request_id: UUID, team_id: int) -> None:
    quarantine_lifts.cancel_lift_request(request_id, team_id=team_id, run_id=run_id)


# --- Baseline ledger ---


def advance_baseline_ledgers_after_push(github_repo_id: int) -> None:
    """Enqueue an advance of every baseline ledger that follows this GitHub repository.

    Call it for a push to the repository's default branch. The lookup is held in the process for
    a minute, so nearly every call costs no query, and a repository without a ledger gets no task.
    """
    ledger_push.advance_after_push(github_repo_id)
