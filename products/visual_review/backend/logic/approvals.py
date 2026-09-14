"""Approving snapshots and finalizing a run (the all-or-nothing baseline commit)."""

from __future__ import annotations

from uuid import UUID

from django.db import transaction
from django.utils import timezone

from ..db import WRITER_DB
from ..facade.enums import ReviewDecision, ReviewState, RunPurpose, RunStatus, SnapshotResult
from ..models import Run
from . import artifact_store, baselines, ci_status, errors, gating, run_queries


@transaction.atomic(using=WRITER_DB)
def finalize_run(
    run_id: UUID,
    user_id: int,
    team_id: int | None = None,
    approve_all: bool = False,
    review_decision: ReviewDecision = ReviewDecision.HUMAN_APPROVED,
    commit_to_github: bool = True,
    add_images_to_comment_on_pr: bool = False,
) -> Run:
    """Finalize a fully-reviewed run: commit the approved baseline and green the gate.

    All-or-nothing by design — a run finalizes only once every changed/new snapshot is
    resolved (approved, tolerated, quarantined, or removed). The committed baseline is
    derived from DB state — exactly the snapshots with ``review_state == APPROVED``, by
    their approved hash — so a tolerated snapshot keeps its existing baseline and is
    never silently overwritten, and the commit always contains the full approved set
    regardless of how many calls it took to review them. A quarantined NEW snapshot that
    was approved by identifier is committed too (see ``_approved_baseline_updates``).

    With ``approve_all=True`` every still-pending changed/new snapshot is approved first
    (tolerated ones are left untouched) — the "approve everything and ship" path. Without
    it, the run must already be fully resolved or this raises RunNotFullyResolvedError.

    Set ``commit_to_github=False`` for CLI auto-approve, which writes the baseline locally
    instead of pushing it to the PR branch.

    The post-approval PR comment is always posted (subject to the existing conditions: repo
    PR comments enabled, run initiated from a GitHub review prompt). ``add_images_to_comment_on_pr``
    only controls whether the before/after snapshot images are embedded in that comment;
    defaults false so the comment stays a text summary unless the reviewer opts in.
    """
    run = run_queries._get_run_for_update(run_id, team_id=team_id)
    repo = run.repo

    if run.purpose == RunPurpose.OBSERVE:
        raise ValueError("Observational runs cannot be approved")

    # Idempotent: a finalized run already committed and posted status — don't redo the work
    # (a second commit, status, and approval comment) on a repeat call.
    if run.approved:
        return run

    if run.status != RunStatus.COMPLETED:
        raise ValueError(f"Run must be completed before approval (current status: {run.status})")

    if run_queries.is_run_stale(run):
        raise errors.StaleRunError("This run has been superseded by a newer run. Approve the latest run instead.")

    # Re-evaluate quarantine so resolution accounting reflects the current policy.
    gating._stamp_quarantine(run)
    now = timezone.now()

    actionable = [
        s
        for s in run.snapshots.using(WRITER_DB).all()
        if s.result in (SnapshotResult.CHANGED, SnapshotResult.NEW) and not s.is_quarantined
    ]

    if approve_all:
        pending = [s for s in actionable if s.review_state not in (ReviewState.APPROVED, ReviewState.TOLERATED)]
        _validate_approval(run, {s.identifier: s.current_hash for s in pending})
        for snapshot in pending:
            snapshot.review_state = ReviewState.APPROVED
            snapshot.reviewed_at = now
            snapshot.reviewed_by_id = user_id
            snapshot.approved_hash = snapshot.current_hash
            snapshot.save(update_fields=["review_state", "reviewed_at", "reviewed_by_id", "approved_hash"])

    # All-or-nothing: refuse to commit while any actionable snapshot is still unreviewed.
    unresolved = [
        s.identifier for s in actionable if s.review_state not in (ReviewState.APPROVED, ReviewState.TOLERATED)
    ]
    if unresolved:
        raise errors.RunNotFullyResolvedError(
            f"Cannot finalize: {len(unresolved)} snapshot(s) still need review — approve or tolerate them first: "
            f"{', '.join(sorted(unresolved)[:10])}"
        )

    # Commit set is derived from DB state, not a caller-supplied list, so it always reflects
    # the full approved set however many calls reviewed it. It reads every snapshot, not only
    # the actionable ones, so an approved quarantined NEW snapshot reaches the commit.
    approved_updates = baselines._approved_baseline_updates(run.snapshots.using(WRITER_DB).all())
    has_removed = run.snapshots.using(WRITER_DB).filter(result=SnapshotResult.REMOVED).exists()

    # Commit first — before DB writes — so a GitHub failure aborts cleanly. Removed snapshots
    # also need a commit, to prune them from the baseline, even when nothing was approved.
    if commit_to_github and (approved_updates or has_removed) and run.pr_number and repo.repo_full_name:
        baselines._commit_baseline_to_github(run, repo, approved_updates, approver_user_id=user_id)

    # Removed snapshots are pruned from the baseline on commit; mark them approved for cleanup.
    run.snapshots.filter(result=SnapshotResult.REMOVED).update(
        review_state=ReviewState.APPROVED,
        reviewed_at=now,
        reviewed_by_id=user_id,
    )

    run.approved = True
    run.review_decision = review_decision
    run.approved_at = now
    run.approved_by_id = user_id
    run.save(update_fields=["approved", "review_decision", "approved_at", "approved_by_id"])

    if commit_to_github:
        ci_status._post_commit_status(run, repo, "success", "Visual changes approved")

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
    """Approve specific snapshots within a run (DB only, no GitHub commit).

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

    now = timezone.now()
    for snapshot in run.snapshots.filter(identifier__in=approvals.keys()):
        new_hash = approvals[snapshot.identifier]
        snapshot.review_state = ReviewState.APPROVED
        snapshot.reviewed_at = now
        snapshot.reviewed_by_id = user_id
        snapshot.approved_hash = new_hash
        snapshot.save(update_fields=["review_state", "reviewed_at", "reviewed_by_id", "approved_hash"])

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

    for identifier, new_hash in approvals.items():
        artifact = artifact_store.get_artifact(repo.id, new_hash)
        if not artifact:
            raise errors.ArtifactNotFoundError(f"Artifact not found for hash {new_hash} (snapshot: {identifier})")
