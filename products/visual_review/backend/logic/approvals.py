"""Review decisions on snapshots, and finalizing a run (the all-or-nothing baseline change).

Finalize commits the baseline file in yaml and shadow mode. Shadow and ledger mode record approval
rows, and in ledger mode those rows are the whole change. In shadow mode recording them never makes
finalize wait or fail.

In ledger mode an accept, a reject or a clear is a decision on one pair of pictures, and it counts on
every run of the pull request that renders the same pair (see `review_decisions`). In yaml and shadow
mode an accept marks the row of the run it was made on, as it always did.
"""

from __future__ import annotations

import dataclasses
from datetime import datetime
from uuid import UUID

from django.db import transaction
from django.db.models import F
from django.utils import timezone

import structlog

from posthog.dataclasses import frozen

from ..db import WRITER_DB
from ..facade.contracts import REASON_MAX_LENGTH
from ..facade.enums import (
    BaselineApprovalState,
    BaselineMode,
    DecisionAction,
    DecisionChannel,
    ReviewDecision,
    ReviewState,
    RunGate,
    RunPurpose,
    RunStatus,
    SnapshotResult,
)
from ..models import BaselineApproval, Run, RunSnapshot
from . import (
    artifact_store,
    baseline_approvals,
    baseline_record,
    baselines,
    ci_status,
    comment_markdown,
    commit_status,
    errors,
    gating,
    github_api,
    ledger,
    review_decisions,
    run_queries,
)
from .review_decisions import Decision, DecisionKey, PullRequestDecisions, RunReview, Standing

logger = structlog.get_logger(__name__)


OBSERVE_RUN_MESSAGE = "This run records the default branch or the merge queue and takes no decisions."


def _short_id(run_id: UUID) -> str:
    return str(run_id)[:8]


def _short_sha(commit_sha: str) -> str:
    return commit_sha[:7]


def _rerun_completing_job(run: Run, check_run_id: str) -> None:
    """Re-run the CI job that completed a finalized run, and log a failure.

    Recompute refuses a finalized run, so after a failure GitHub's "Re-run failed jobs"
    is the way to clear the required check.
    """
    triggered, error = ci_status._rerun_github_job(run, check_run_id)
    if not triggered:
        logger.warning("visual_review.finalize_ci_rerun_failed", run_id=str(run.id), error=error)


def _record_shadow_approvals(run: Run, user_id: int, carried_commit_sha: str) -> None:
    """Write a shadow-mode finalize's approval rows, never failing the finalize.

    The savepoint keeps a failed statement from aborting the finalize transaction, which already
    pushed its baseline commit.
    """
    try:
        with transaction.atomic(using=WRITER_DB):
            baseline_approvals.record_approvals(run, user_id, carried_commit_sha=carried_commit_sha)
    except Exception:
        logger.warning("visual_review.shadow_approvals_failed", run_id=str(run.id), exc_info=True)


@frozen
class _FinalizeContext:
    """What finalize reads before its transaction.

    The mode decides whether the ledger lock comes first. The pull request is read in ledger mode only.
    """

    repo_id: UUID
    mode: BaselineMode
    run_type: str
    pr_number: int | None
    pull_request: github_api.PullRequestState | None = None


def _read_finalize_context(run_id: UUID, team_id: int | None) -> _FinalizeContext:
    """Read the mode and, in ledger mode, the pull request outside the transaction, so no lock waits on GitHub.

    In yaml and shadow mode the commit path reads the pull request itself, so nothing is read here.
    """
    run = run_queries.get_run(run_id, team_id=team_id)
    mode = BaselineMode(run.repo.baseline_mode)
    context = _FinalizeContext(repo_id=run.repo_id, mode=mode, run_type=run.run_type, pr_number=run.pr_number)
    if mode != BaselineMode.LEDGER or run.pr_number is None or run.approved:
        return context
    pull_request = github_api.pull_request_state(run.repo, run.pr_number)
    if pull_request is None:
        raise errors.GitHubCommitError(f"GitHub did not return pull request #{run.pr_number}.")
    return _FinalizeContext(
        repo_id=run.repo_id, mode=mode, run_type=run.run_type, pr_number=run.pr_number, pull_request=pull_request
    )


def _require_open_pull_request_at_run(run: Run, pull_request: github_api.PullRequestState) -> None:
    if pull_request.state != "open" or pull_request.merged:
        raise errors.PullRequestClosedError(baselines.PULL_REQUEST_CLOSED_MESSAGE.format(pr_number=run.pr_number))
    if pull_request.head_sha != run.commit_sha:
        raise errors.PRSHAMismatchError(
            baselines.PR_SHA_MISMATCH_MESSAGE.format(expected=run.commit_sha, actual=pull_request.head_sha)
        )


def _stale_run_error(run: Run) -> errors.StaleRunError:
    if run.pr_number is None:
        return errors.StaleRunError("This run has been superseded by a newer run. Approve the latest run instead.")
    head = review_decisions.head_run(run)
    return errors.StaleRunError(
        f"Run {_short_id(run.id)} is not the newest run of PR #{run.pr_number}. "
        f"Finalize run {_short_id(head.id)} ({_short_sha(head.commit_sha)}) instead.",
        head_run_id=head.id,
        head_commit_sha=head.commit_sha,
    )


def _decision(
    action: DecisionAction,
    key: DecisionKey,
    *,
    user_id: int,
    via: DecisionChannel,
    reason: str,
    seq: int,
    run: Run,
    at: datetime,
) -> Decision:
    return Decision(
        action=action,
        key=key,
        by_id=user_id,
        via=via,
        reason=reason,
        at=at,
        seq=seq,
        run_id=run.id,
        commit_sha=run.commit_sha,
    )


def _may_fill(snapshot: review_decisions.SnapshotReview, via: DecisionChannel) -> bool:
    """Whether "accept all" may accept a snapshot nobody accepted. An agent leaves a person's undo alone."""
    decision = snapshot.effective.decision
    return not (via == DecisionChannel.MCP and decision is not None and decision.by_person)


def _accept_for_finalize(
    run: Run, user_id: int, via: DecisionChannel, decisions: PullRequestDecisions, approve_all: bool
) -> None:
    """Accept what finalize accepts by itself: removals nobody rejected, and with `approve_all` every open change.

    Neither ever replaces a rejection, and an agent never replaces a person's undo.
    """
    review = review_decisions.review_run(run, decisions)
    removals = [
        snapshot
        for snapshot in review.snapshots
        if snapshot.result == SnapshotResult.REMOVED
        and not snapshot.effective.rejected
        and not snapshot.effective.accepted
        and _may_fill(snapshot, via)
    ]
    fills = []
    if approve_all:
        fills = [
            snapshot
            for snapshot in review.with_standing(Standing.NEEDS_REVIEW)
            if snapshot.result != SnapshotResult.REMOVED and _may_fill(snapshot, via)
        ]
    if not removals and not fills:
        return
    missing = set(artifact_store.find_missing_hashes(run.repo_id, [snapshot.key.new_hash for snapshot in fills]))
    for snapshot in fills:
        if snapshot.key.new_hash in missing:
            raise errors.ArtifactNotFoundError(
                f"Artifact not found for hash {snapshot.key.new_hash} (snapshot: {snapshot.identifier})"
            )
    rows = {
        row.identifier: row
        for row in run.snapshots.using(WRITER_DB).filter(
            identifier__in=[snapshot.identifier for snapshot in [*removals, *fills]]
        )
    }
    at = review_decisions.database_now()
    review_decisions.append_decisions(
        [
            (
                rows[snapshot.identifier],
                _decision(
                    DecisionAction.ACCEPT,
                    snapshot.key,
                    user_id=user_id,
                    via=via,
                    reason="",
                    seq=decisions.max_seq + index,
                    run=run,
                    at=at,
                ),
            )
            for index, snapshot in enumerate([*removals, *fills], start=1)
        ]
    )


def _write_effective_states(run: Run, decisions: PullRequestDecisions) -> None:
    """Write the effective decision onto each changed, new and removed row, which the commit path reads."""
    rows = list(run.snapshots.using(WRITER_DB).exclude(result=SnapshotResult.UNCHANGED))
    for row in rows:
        effective = decisions.effective(review_decisions.key_of(row.identifier, row.baseline_hash, row.current_hash))
        decision = effective.decision
        if effective.rejected and decision is not None:
            row.review_state = ReviewState.REJECTED
            row.reviewed_by_id = decision.by_id
            row.reviewed_at = decision.at
            row.review_comment = decision.reason
            row.approved_hash = ""
        elif effective.accepted and decision is not None:
            row.review_state = ReviewState.APPROVED
            row.reviewed_by_id = decision.by_id
            row.reviewed_at = decision.at
            row.review_comment = ""
            row.approved_hash = decision.key.new_hash
        elif row.review_state != ReviewState.TOLERATED:
            row.review_state = ReviewState.PENDING
            row.reviewed_by_id = None
            row.reviewed_at = None
            row.review_comment = ""
            row.approved_hash = ""
    RunSnapshot.objects.using(WRITER_DB).bulk_update(
        rows, ["review_state", "reviewed_by_id", "reviewed_at", "review_comment", "approved_hash"]
    )


def _count_text(count: int, singular: str, plural: str) -> str:
    return f"{count} {singular if count == 1 else plural}"


def _not_fully_resolved(run: Run, review: RunReview) -> errors.RunNotFullyResolvedError:
    rejections = review.rejections()
    needs_review = sorted(snapshot.identifier for snapshot in review.with_standing(Standing.NEEDS_REVIEW))
    parts = []
    if rejections:
        parts.append(f"{_count_text(len(rejections), 'change is', 'changes are')} rejected")
    if needs_review:
        parts.append(f"{_count_text(len(needs_review), 'change needs', 'changes need')} review")
    return errors.RunNotFullyResolvedError(
        f"Cannot finalize run {_short_sha(run.commit_sha)}: {' and '.join(parts)}.",
        rejected=[
            errors.RejectedSnapshot(identifier=decision.key.identifier, by_id=decision.by_id, reason=decision.reason)
            for decision in rejections
        ],
        needs_review=needs_review,
    )


def _settle_decisions(run: Run, user_id: int, via: DecisionChannel, approve_all: bool) -> None:
    """Make the head run's rows say what the pull request's decisions say, or refuse the finalize.

    The caller holds the pull request lock, so no decision lands between this read and the commit.
    """
    _accept_for_finalize(run, user_id, via, review_decisions.pull_request_decisions(run), approve_all)
    decisions = review_decisions.pull_request_decisions(run)
    _write_effective_states(run, decisions)
    review = review_decisions.review_run(run, decisions)
    if review.rejected_count or review.needs_review_count:
        raise _not_fully_resolved(run, review)


def _resolve_rows(run: Run, user_id: int, approve_all: bool, now: datetime) -> None:
    """Finalize's check in yaml and shadow mode, where each row holds its own review state."""
    actionable = [
        s
        for s in run.snapshots.using(WRITER_DB).all()
        if s.result in (SnapshotResult.CHANGED, SnapshotResult.NEW) and not s.is_quarantined
    ]

    if approve_all:
        pending = [s for s in actionable if s.review_state not in (ReviewState.APPROVED, ReviewState.TOLERATED)]
        _validate_approval(run, {s.identifier: s.current_hash for s in pending})
        # One statement for all pending snapshots, because in ledger mode this runs under the repo-wide
        # ledger lock. The objects get the same values, because the check below reads them.
        run.snapshots.using(WRITER_DB).filter(id__in=[s.id for s in pending]).update(
            review_state=ReviewState.APPROVED,
            reviewed_at=now,
            reviewed_by_id=user_id,
            approved_hash=F("current_hash"),
        )
        for snapshot in pending:
            snapshot.review_state = ReviewState.APPROVED
            snapshot.reviewed_at = now
            snapshot.reviewed_by_id = user_id
            snapshot.approved_hash = snapshot.current_hash

    # All-or-nothing: refuse to commit while any actionable snapshot is still unreviewed.
    unresolved = sorted(
        s.identifier for s in actionable if s.review_state not in (ReviewState.APPROVED, ReviewState.TOLERATED)
    )
    if unresolved:
        raise errors.RunNotFullyResolvedError(
            f"Cannot finalize run {_short_sha(run.commit_sha)}: "
            f"{_count_text(len(unresolved), 'change needs', 'changes need')} review.",
            needs_review=unresolved,
        )


def finalize_run(
    run_id: UUID,
    user_id: int,
    team_id: int | None = None,
    approve_all: bool = False,
    review_decision: ReviewDecision = ReviewDecision.HUMAN_APPROVED,
    commit_to_github: bool = True,
    add_images_to_comment_on_pr: bool = False,
    via: DecisionChannel = DecisionChannel.WEB,
) -> Run:
    """Finalize a fully-reviewed run: commit the approved baseline and green the gate.

    All-or-nothing by design — a run finalizes only once every changed/new snapshot is
    resolved (approved, tolerated, quarantined, or removed). The committed baseline is
    derived from DB state — exactly the snapshots with ``review_state == APPROVED``, by
    their approved hash — so a tolerated snapshot keeps its existing baseline and is
    never silently overwritten, and the commit always contains the full approved set
    regardless of how many calls it took to review them. A quarantined snapshot that
    was approved by identifier is committed too (see ``_approved_baseline_updates``).

    With ``approve_all=True`` every still-pending changed/new snapshot is approved first
    (tolerated ones are left untouched) — the "approve everything and ship" path. Without
    it, the run must already be fully resolved or this raises RunNotFullyResolvedError.

    In ledger mode the pull request's decisions decide: an accept made on an earlier run of the
    pull request counts while the pictures are the same, a rejection always refuses the finalize,
    and ``approve_all`` never replaces a rejection. Removals are accepted unless someone rejected them.

    Set ``commit_to_github=False`` for CLI auto-approve, which writes the baseline locally
    instead of pushing it to the PR branch.

    The post-approval PR comment is posted when the repo has PR comments enabled and
    ``commit_to_github`` is true. It updates the run's review prompt when the run has one, and
    posts a new comment when it does not. ``add_images_to_comment_on_pr`` only controls whether
    the before/after snapshot images are embedded in that comment; defaults false so the comment
    stays a text summary unless the reviewer opts in.

    In shadow and ledger mode finalize also writes one approval row per approved change. In
    ledger mode nothing is committed and nothing in CI runs again: the success status is the gate.
    """
    context = _read_finalize_context(run_id, team_id)
    return _finalize_run(
        run_id,
        user_id,
        team_id=team_id,
        approve_all=approve_all,
        review_decision=review_decision,
        commit_to_github=commit_to_github,
        add_images_to_comment_on_pr=add_images_to_comment_on_pr,
        context=context,
        via=via,
    )


@transaction.atomic(using=WRITER_DB)
def _finalize_run(
    run_id: UUID,
    user_id: int,
    *,
    team_id: int | None,
    approve_all: bool,
    review_decision: ReviewDecision,
    commit_to_github: bool,
    add_images_to_comment_on_pr: bool,
    context: _FinalizeContext,
    via: DecisionChannel,
) -> Run:
    mode = context.mode
    ledger_locked = False
    if mode == BaselineMode.LEDGER:
        ledger.lock_ledger(context.repo_id)
        ledger_locked = True
        if context.pr_number is not None:
            review_decisions.lock_pull_request(context.repo_id, context.run_type, context.pr_number)
    elif mode == BaselineMode.SHADOW:
        # Shadow mode must never make finalize wait on the ledger, so it only takes a free lock.
        ledger_locked = ledger.try_lock_ledger(context.repo_id)
        if not ledger_locked:
            logger.info("visual_review.shadow_approvals_skipped_ledger_busy", run_id=str(run_id))
    run = run_queries._get_run_for_update(run_id, team_id=team_id)
    repo = run.repo
    # The locks above follow the mode read before the transaction. A mode that differs now changed
    # before finalize held them, so neither the lock order with `advance` nor the pull request lock
    # that decision writes need is guaranteed.
    if repo.baseline_mode != mode:
        raise errors.BaselineModeChangedError("The repo's baseline mode changed during the approval. Try again.")

    if run.purpose == RunPurpose.OBSERVE:
        raise ValueError("Observational runs cannot be approved")

    # Idempotent: a finalized run already committed and posted status — don't redo the work
    # (a second commit, status, and approval comment) on a repeat call.
    if run.approved:
        return run

    if run.status != RunStatus.COMPLETED:
        raise ValueError(f"Run must be completed before approval (current status: {run.status})")

    if run_queries.is_run_stale(run):
        raise _stale_run_error(run)

    if mode == BaselineMode.LEDGER:
        if run.pr_number is None:
            raise errors.RunWithoutPullRequestError(
                "This run has no pull request, and in ledger mode an approval belongs to a pull request. "
                "Approve a run of the pull request that makes this change."
            )
        if context.pull_request is not None:
            _require_open_pull_request_at_run(run, context.pull_request)
        if baseline_record.record_for_run(run) is None:
            raise errors.RunWithoutBaselineRecordError(
                "This run finished before the repo used the baseline ledger, so its approvals cannot be recorded. "
                f"Re-run CI on commit {run.commit_sha[:12]} and approve the new run."
            )

    # Re-evaluate quarantine so resolution accounting reflects the current policy.
    gating._stamp_quarantine(run)
    now = timezone.now()
    decides_by_pull_request = review_decisions.decides_by_pull_request(run)

    if decides_by_pull_request:
        _settle_decisions(run, user_id, via, approve_all)
    else:
        _resolve_rows(run, user_id, approve_all, now)

    # Commit set is derived from DB state, not a caller-supplied list, so it always reflects
    # the full approved set however many calls reviewed it. It reads every snapshot, not only
    # the actionable ones, so an approved quarantined snapshot reaches the commit.
    approved_updates = baselines._approved_baseline_updates(run.snapshots.using(WRITER_DB).all())
    has_removed = run.snapshots.using(WRITER_DB).filter(result=SnapshotResult.REMOVED).exists()

    # Commit first — before DB writes — so a GitHub failure aborts cleanly. Removed snapshots
    # also need a commit, to prune them from the baseline, even when nothing was approved.
    # In ledger mode the approval rows are the baseline change, so nothing goes to the branch.
    committed = bool(
        mode != BaselineMode.LEDGER
        and commit_to_github
        and (approved_updates or has_removed)
        and run.pr_number
        and repo.repo_full_name
    )
    if committed:
        baselines._commit_baseline_to_github(run, repo, approved_updates, approver_user_id=user_id)

    if not decides_by_pull_request:
        # Removed snapshots are pruned from the baseline on commit; mark them approved for cleanup.
        run.snapshots.filter(result=SnapshotResult.REMOVED).update(
            review_state=ReviewState.APPROVED,
            reviewed_at=now,
            reviewed_by_id=user_id,
        )

    # Landing without evidence needs the merged head to be the approval's commit or carried commit.
    carried_commit_sha = ((run.metadata or {}).get("baseline_commit_sha") or "") if committed else ""
    if mode == BaselineMode.LEDGER:
        baseline_approvals.record_approvals(
            run, user_id, carried_commit_sha=carried_commit_sha, name_deciders=decides_by_pull_request
        )

    run.approved = True
    run.review_decision = review_decision
    run.approved_at = now
    run.approved_by_id = user_id
    run.save(update_fields=["approved", "review_decision", "approved_at", "approved_by_id"])

    if mode == BaselineMode.SHADOW and ledger_locked:
        _record_shadow_approvals(run, user_id, carried_commit_sha)

    if commit_status.publishes_by_commit(repo):
        commit_status.publish_for_run(run)
    elif commit_to_github:
        ci_status._post_commit_status(run, repo, "success", "Visual changes approved")

    # A baseline commit starts a new CI run. Without one, the job that completed a `ci_job` run
    # keeps the red verdict it read before the review, so it has to read it again. A
    # `commit_status` run is gated by the status, so nothing in CI runs again.
    check_run_id = (run.metadata or {}).get("github_check_run_id")
    if run.gate == RunGate.CI_JOB and commit_to_github and not committed and run.pr_number and check_run_id:
        transaction.on_commit(lambda: _rerun_completing_job(run, str(check_run_id)), using=WRITER_DB)

    if commit_to_github and review_decision == ReviewDecision.HUMAN_APPROVED:
        from ..tasks.tasks import post_approval_comment

        run_id_str = str(run.id)
        run_team_id = run.team_id
        add_images = add_images_to_comment_on_pr
        transaction.on_commit(
            lambda: post_approval_comment.delay(run_team_id, run_id_str, add_images),
            using=WRITER_DB,
        )

    return run


@transaction.atomic(using=WRITER_DB)
def approve_snapshots(run_id: UUID, user_id: int, approved_snapshots: list[dict], team_id: int | None = None) -> Run:
    """Approve specific snapshots within a run (DB only, no GitHub commit), in yaml and shadow mode.

    Used for per-snapshot "Accept change" in the UI. Does not finalize
    the run — that happens via finalize_run.
    """
    run = run_queries._get_run_for_update(run_id, team_id=team_id)

    if run.purpose == RunPurpose.OBSERVE:
        raise ValueError("Observational runs cannot be approved")

    if run_queries.is_run_stale(run):
        raise errors.StaleRunError("This run has been superseded by a newer run. Approve the latest run instead.")

    approvals = {s["identifier"]: s["new_hash"] for s in approved_snapshots}
    _validate_approval(run, approvals)
    refusals = _baseline_refusals(run, approved_snapshots)
    if refusals:
        raise errors.DecisionRefusedError(refusals)

    now = timezone.now()
    for snapshot in run.snapshots.filter(identifier__in=approvals.keys()):
        new_hash = approvals[snapshot.identifier]
        snapshot.review_state = ReviewState.APPROVED
        snapshot.reviewed_at = now
        snapshot.reviewed_by_id = user_id
        snapshot.approved_hash = new_hash
        snapshot.save(update_fields=["review_state", "reviewed_at", "reviewed_by_id", "approved_hash"])

    commit_status.publish_for_run(run)

    return run


def _validate_approval(run: Run, approvals: dict[str, str]) -> None:
    """Validate snapshot identifiers, hash matches, and artifact existence."""
    repo = run.repo

    run_identifiers = set(run.snapshots.values_list("identifier", flat=True))
    unknown = set(approvals.keys()) - run_identifiers
    if unknown:
        raise ValueError(f"Unknown snapshot identifiers: {', '.join(sorted(unknown))}")

    for snapshot in run.snapshots.filter(identifier__in=approvals.keys()):
        expected_hash = approvals[snapshot.identifier]
        if expected_hash != snapshot.current_hash:
            raise ValueError(
                f"Hash mismatch for {snapshot.identifier}: "
                f"approved {expected_hash[:12]} but current is {snapshot.current_hash[:12]}"
            )

    missing_hashes = set(artifact_store.find_missing_hashes(repo.id, list(approvals.values())))
    for identifier, new_hash in approvals.items():
        if new_hash in missing_hashes:
            raise errors.ArtifactNotFoundError(f"Artifact not found for hash {new_hash} (snapshot: {identifier})")


def _baseline_refusals(run: Run, approved_snapshots: list[dict]) -> list[errors.DecisionRefusal]:
    """Refuse an accept whose `old_hash` names another baseline than the one the snapshot compares against."""
    old_hashes = {s["identifier"]: s["old_hash"] for s in approved_snapshots if s.get("old_hash") is not None}
    if not old_hashes:
        return []
    baselines = dict(run.snapshots.filter(identifier__in=old_hashes).values_list("identifier", "baseline_hash"))
    return [
        errors.DecisionRefusal(
            identifier=identifier,
            code="hash_mismatch",
            detail=(
                f"{identifier} on run {_short_id(run.id)} compares against "
                f"{baselines[identifier][:12] or 'no baseline'}, not {old_hash[:12] or 'no baseline'}. "
                "Read the snapshot again from the run you pass as id."
            ),
            conflict=False,
        )
        for identifier, old_hash in old_hashes.items()
        if old_hash != baselines[identifier]
    ]


@frozen
class DecisionRequest:
    """One snapshot of a decision call. A `new_hash` of None stands for a removed snapshot."""

    identifier: str
    new_hash: str | None = None
    # When set, the baseline the caller saw, so a decision never lands on a pair the caller did not look at.
    old_hash: str | None = None
    reason: str = ""


@frozen
class DecisionOutcome:
    run: Run
    head: Run
    head_review: RunReview
    # Snapshots whose newest decision already was this one, so nothing was written for them.
    already_decided: tuple[str, ...]


@frozen
class _DecisionCall:
    action: DecisionAction
    user_id: int
    via: DecisionChannel
    expected_seq: int | None
    override_rejection: bool
    run: Run


def _refused(code: str, detail: str, *, identifier: str = "", conflict: bool) -> errors.DecisionRefusedError:
    return errors.DecisionRefusedError(
        [errors.DecisionRefusal(identifier=identifier, code=code, detail=detail, conflict=conflict)]
    )


def _unknown_identifier(run: Run, identifier: str) -> errors.DecisionRefusal:
    return errors.DecisionRefusal(
        identifier=identifier,
        code="unknown_identifier",
        detail=f"Run {_short_id(run.id)} has no snapshot named {identifier}.",
        conflict=False,
    )


def _check_pictures(call: _DecisionCall, request: DecisionRequest, row: RunSnapshot) -> errors.DecisionRefusal | None:
    """Refuse a request for a pair of pictures the run does not show."""
    run = call.run
    identifier = request.identifier
    # A tolerated or absorbed difference is unchanged with two different pictures. It still takes a
    # decision, because a rejection of that pair blocks the run and has to be undone where it shows.
    if row.result == SnapshotResult.UNCHANGED and row.baseline_hash == row.current_hash:
        return errors.DecisionRefusal(
            identifier=identifier,
            code="not_a_change",
            detail=(
                f"{identifier} is unchanged on run {_short_id(run.id)}. "
                "Only changed, new and removed snapshots take a decision."
            ),
            conflict=False,
        )
    if call.action == DecisionAction.CLEAR:
        return None
    run_label = f"run {_short_id(run.id)} ({_short_sha(run.commit_sha)})"
    read_again = "Read the snapshot again from the run you pass as id."
    if row.result == SnapshotResult.REMOVED and request.new_hash:
        return errors.DecisionRefusal(
            identifier=identifier,
            code="hash_mismatch",
            detail=f"{identifier} is removed on {run_label}, so new_hash must be null. {read_again}",
            conflict=False,
        )
    if row.result != SnapshotResult.REMOVED and not request.new_hash:
        return errors.DecisionRefusal(
            identifier=identifier,
            code="hash_required",
            detail=(
                f"{identifier} is {row.result} on this run, so new_hash is required. "
                "Use null only for a removed snapshot."
            ),
            conflict=False,
        )
    if row.result != SnapshotResult.REMOVED and request.new_hash != row.current_hash:
        return errors.DecisionRefusal(
            identifier=identifier,
            code="hash_mismatch",
            detail=(
                f"{identifier} on {run_label} renders {row.current_hash[:12]}, not {(request.new_hash or '')[:12]}. "
                f"{read_again}"
            ),
            conflict=False,
        )
    if request.old_hash is not None and request.old_hash != row.baseline_hash:
        return errors.DecisionRefusal(
            identifier=identifier,
            code="hash_mismatch",
            detail=(
                f"{identifier} on {run_label} compares against {row.baseline_hash[:12] or 'no baseline'}, "
                f"not {request.old_hash[:12] or 'no baseline'}. {read_again}"
            ),
            conflict=False,
        )
    if call.action == DecisionAction.REJECT and not request.reason.strip():
        return errors.DecisionRefusal(
            identifier=identifier,
            code="reason_required",
            detail="A reject needs a reason the author can act on.",
            conflict=False,
        )
    return None


def _describe(decision: Decision, names: dict[int, str]) -> str:
    who = names.get(decision.by_id, "Someone") if decision.by_id is not None else "Someone"
    where = f"{decision.key.identifier} on {_short_sha(decision.commit_sha)}"
    if decision.action == DecisionAction.REJECT:
        return f'{who} rejected {where}: "{decision.reason}"'
    if decision.action == DecisionAction.ACCEPT:
        return f"{who} accepted {where}"
    return f"{who} undid the decision on {where}"


def _already_holds(action: DecisionAction, current: Decision | None) -> bool:
    """Whether the pair's newest decision already is the one asked for, so nothing needs writing."""
    if action == DecisionAction.CLEAR:
        return current is None or current.action == DecisionAction.CLEAR
    return current is not None and current.action == action


def _check_against_current(
    call: _DecisionCall, identifier: str, current: Decision | None, covered: bool, names: dict[int, str]
) -> errors.DecisionRefusal | None:
    """Refuse a decision that may not replace the newest one on its pair. None lets it stand.

    A pure function of the call and the pair's newest decision, so each rule is one row of a table test.
    An agent never undoes or accepts over a rejection it did not make, and never accepts over its own:
    taking a rejection back that way needs a person.
    """

    def refusal(code: str, detail: str) -> errors.DecisionRefusal:
        return errors.DecisionRefusal(
            identifier=identifier,
            code=code,
            detail=detail,
            conflict=True,
            current_seq=current.seq if current is not None else None,
        )

    if covered:
        return refusal(
            "run_finalized",
            f"{identifier} is part of a finalized run of PR #{call.run.pr_number}, so its decision is fixed. "
            "Push a new commit to change it.",
        )
    if call.expected_seq is not None and current is not None and current.seq > call.expected_seq:
        return refusal(
            "decided_since",
            f"{_describe(current, names)} after you read it. Read the snapshot again and decide on what it shows now.",
        )
    if current is None or _already_holds(call.action, current):
        return None
    agent = call.via == DecisionChannel.MCP
    if agent and current.by_person:
        who = names.get(current.by_id, "the person") if current.by_id is not None else "the person"
        return refusal(
            "decided_by_person",
            f"{_describe(current, names)}. An agent cannot change a person's decision. "
            f"Fix the code and push, or ask {who} or the user to decide.",
        )
    if current.action != DecisionAction.REJECT:
        return None
    by_other = current.by_id != call.user_id
    if agent and (call.action == DecisionAction.ACCEPT or by_other):
        return refusal(
            "rejected_by_other",
            f"{_describe(current, names)}. An agent cannot accept over a rejection or undo someone else's. "
            "Ask the user to decide.",
        )
    if by_other and not call.override_rejection:
        verb = "accept" if call.action == DecisionAction.ACCEPT else "undo"
        return refusal(
            "rejected_by_other", f"{_describe(current, names)}. Pass override_rejection to {verb} it anyway."
        )
    return None


def _keys_covered_by_approvals(run: Run, pr_number: int, identifiers: list[str]) -> set[DecisionKey]:
    """The pairs an open or promoted approval row of the run's pull request holds. A finalize fixed them."""
    rows = BaselineApproval.objects.using(WRITER_DB).filter(
        team_id=run.team_id,
        repo_id=run.repo_id,
        run_type=run.run_type,
        pr_number=pr_number,
        identifier__in=identifiers,
        state__in=(BaselineApprovalState.OPEN, BaselineApprovalState.PROMOTED),
    )
    return {
        review_decisions.key_of(identifier, effective_base_hash, content_hash)
        for identifier, effective_base_hash, content_hash in rows.values_list(
            "identifier", "effective_base_hash", "content_hash"
        )
    }


def _pull_request_head_sha(run: Run) -> str | None:
    """The pull request's head commit, or None when GitHub cannot say. Refuses a merged or closed pull request."""
    try:
        pull_request = github_api.pull_request_state(run.repo, run.pr_number or 0)
    except github_api.GITHUB_READ_REFUSED:
        return None
    if pull_request is None:
        return None
    if pull_request.state != "open" or pull_request.merged:
        raise _refused(
            "pr_closed",
            f"PR #{run.pr_number} is merged or closed, so its decisions can no longer change.",
            conflict=True,
        )
    return pull_request.head_sha


def _lock_run(run_id: UUID, team_id: int) -> Run:
    """Lock the run row without its repo row, which `advance` takes a share lock on under the ledger lock."""
    try:
        return (
            Run.objects.using(WRITER_DB)
            .select_for_update(of=("self",))
            .select_related("repo")
            .get(id=run_id, team_id=team_id)
        )
    except Run.DoesNotExist as e:
        raise errors.RunNotFoundError(f"Run {run_id} not found") from e


def _missing_artifact_refusals(run: Run, writes: list[tuple[RunSnapshot, DecisionKey]]) -> list[errors.DecisionRefusal]:
    hashes = [key.new_hash for _row, key in writes if key.new_hash]
    missing = set(artifact_store.find_missing_hashes(run.repo_id, hashes))
    return [
        errors.DecisionRefusal(
            identifier=key.identifier,
            code="artifact_not_found",
            detail=f"Artifact not found for hash {key.new_hash} (snapshot: {key.identifier}).",
            conflict=False,
        )
        for _row, key in writes
        if key.new_hash in missing
    ]


@transaction.atomic(using=WRITER_DB)
def _decide_on_pull_request(
    call: _DecisionCall, requests: list[DecisionRequest], head_sha: str | None
) -> DecisionOutcome:
    pr_number = call.run.pr_number
    assert pr_number is not None
    review_decisions.lock_pull_request(call.run.repo_id, call.run.run_type, pr_number)
    run = _lock_run(call.run.id, call.run.team_id)
    call = dataclasses.replace(call, run=run)
    head = review_decisions.head_run(run, head_sha)
    if head.approved:
        raise _refused(
            "run_finalized",
            f"The newest run of PR #{pr_number} ({_short_sha(head.commit_sha)}) is finalized, so decisions on this "
            "pull request are fixed. Push a new commit to change one.",
            conflict=True,
        )

    decisions = review_decisions.pull_request_decisions(run)
    identifiers = [request.identifier for request in requests]
    rows = {row.identifier: row for row in run.snapshots.using(WRITER_DB).filter(identifier__in=identifiers)}
    covered = _keys_covered_by_approvals(run, pr_number, identifiers)
    currents = {
        identifier: decisions.newest(review_decisions.key_of(identifier, row.baseline_hash, row.current_hash))
        for identifier, row in rows.items()
    }
    names = comment_markdown.approver_labels(
        {decision.by_id for decision in currents.values() if decision is not None and decision.by_id is not None}
    )

    refusals: list[errors.DecisionRefusal] = []
    writes: list[tuple[RunSnapshot, DecisionKey]] = []
    already: list[str] = []
    replaces_rejection = False
    for request in requests:
        row = rows.get(request.identifier)
        if row is None:
            refusals.append(_unknown_identifier(run, request.identifier))
            continue
        refusal = _check_pictures(call, request, row)
        if refusal is not None:
            refusals.append(refusal)
            continue
        key = review_decisions.key_of(row.identifier, row.baseline_hash, row.current_hash)
        current = currents.get(request.identifier)
        refusal = _check_against_current(call, request.identifier, current, key in covered, names)
        if refusal is not None:
            refusals.append(refusal)
        elif _already_holds(call.action, current):
            already.append(request.identifier)
        else:
            writes.append((row, key))
            replaces_rejection = replaces_rejection or (current is not None and current.action == DecisionAction.REJECT)
    if call.action == DecisionAction.ACCEPT:
        refusals.extend(_missing_artifact_refusals(run, writes))
    if refusals:
        raise errors.DecisionRefusedError(refusals)

    reasons = {request.identifier: request.reason.strip()[:REASON_MAX_LENGTH] for request in requests}
    at = review_decisions.database_now()
    review_decisions.append_decisions(
        [
            (
                row,
                _decision(
                    call.action,
                    key,
                    user_id=call.user_id,
                    via=call.via,
                    reason=reasons[row.identifier] if call.action == DecisionAction.REJECT else "",
                    seq=decisions.max_seq + index,
                    run=run,
                    at=at,
                ),
            )
            for index, (row, key) in enumerate(writes, start=1)
        ]
    )

    if writes:
        commit_status.publish_for_run(head)
    return DecisionOutcome(
        run=run,
        head=head,
        head_review=review_decisions.review_run(head),
        already_decided=tuple(already),
    )


def _unique_requests(requests: list[DecisionRequest]) -> list[DecisionRequest]:
    """One request per snapshot. A later request for the same snapshot wins."""
    return list({request.identifier: request for request in requests}.values())


def decide(
    run_id: UUID,
    user_id: int,
    action: DecisionAction,
    requests: list[DecisionRequest],
    *,
    via: DecisionChannel,
    team_id: int,
    expected_seq: int | None = None,
    override_rejection: bool = False,
) -> DecisionOutcome:
    """Accept, reject or clear snapshots of a run, all or nothing.

    In ledger mode the decision is about the pair of pictures the run shows, and it counts on every
    run of the pull request that renders the same pair, also when it is made on a superseded run.
    A decision republishes the status of the pull request's head run, not of the run it was made on.
    `expected_seq` is the newest `seq` the caller saw on these snapshots, or 0 when it saw none, so
    a decision someone made after that read is not replaced unseen.

    In yaml and shadow mode only an accept exists, and it marks the run's own rows.
    """
    run = run_queries.get_run(run_id, team_id=team_id)
    if run.purpose == RunPurpose.OBSERVE:
        raise _refused("observe_run", OBSERVE_RUN_MESSAGE, conflict=False)
    requests = _unique_requests(requests)
    if not review_decisions.decides_by_pull_request(run):
        if action != DecisionAction.ACCEPT:
            raise _refused(
                "not_ledger_mode",
                "Rejects and undos work in ledger mode only. This repo reads its baselines from the baseline file.",
                conflict=False,
            )
        without_hash = [request.identifier for request in requests if not request.new_hash]
        if without_hash:
            raise errors.DecisionRefusedError(
                [
                    errors.DecisionRefusal(
                        identifier=identifier,
                        code="hash_required",
                        detail=(
                            f"{identifier} needs its new_hash. In yaml and shadow mode finalize accepts removed "
                            "snapshots by itself, so only changed and new snapshots take an accept."
                        ),
                        conflict=False,
                    )
                    for identifier in without_hash
                ]
            )
        approved = approve_snapshots(
            run_id,
            user_id,
            [
                {"identifier": request.identifier, "new_hash": request.new_hash, "old_hash": request.old_hash}
                for request in requests
            ],
            team_id=team_id,
        )
        return DecisionOutcome(
            run=approved, head=approved, head_review=review_decisions.review_run(approved), already_decided=()
        )
    if run.status != RunStatus.COMPLETED:
        raise _refused(
            "run_not_ready",
            f"Run {_short_id(run.id)} is {run.status}. Decide once its status is completed.",
            conflict=True,
        )
    head_sha = _pull_request_head_sha(run)
    call = _DecisionCall(
        action=action,
        user_id=user_id,
        via=via,
        expected_seq=expected_seq,
        override_rejection=override_rejection,
        run=run,
    )
    return _decide_on_pull_request(call, requests, head_sha)
