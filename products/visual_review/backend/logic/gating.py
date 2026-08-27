"""Quarantine stamping, resolution accounting, and the commit status that gates CI."""

from __future__ import annotations

from django.db.models import Q
from django.utils import timezone

from ..db import WRITER_DB
from ..facade.enums import ReviewState, RunPurpose, SnapshotResult, ToleratedReason
from ..models import QuarantinedIdentifier, Run, RunSnapshot
from . import baselines, ci_status, comment_markdown, comments


def _stamp_quarantine(run: Run) -> None:
    """Evaluate quarantine policy and freeze it on each snapshot."""
    now = timezone.now()
    quarantined_ids = set(
        QuarantinedIdentifier.objects.using(WRITER_DB)
        .filter(repo_id=run.repo_id, run_type=run.run_type, team_id=run.team_id)
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
        .values_list("identifier", flat=True)
    )

    if not quarantined_ids:
        run.snapshots.using(WRITER_DB).filter(is_quarantined=True).update(is_quarantined=False)
        return

    snapshots = run.snapshots.using(WRITER_DB)
    snapshots.filter(identifier__in=quarantined_ids, is_quarantined=False).update(is_quarantined=True)
    snapshots.filter(is_quarantined=True).exclude(identifier__in=quarantined_ids).update(is_quarantined=False)


def _is_unresolved(s: RunSnapshot) -> bool:
    """A snapshot is unresolved if it represents a change that hasn't been dealt with."""
    if s.result == SnapshotResult.UNCHANGED:
        return False
    if s.is_quarantined:
        return False
    if s.review_state in (ReviewState.TOLERATED, ReviewState.APPROVED):
        return False
    return True


def _changes_summary(run: Run) -> str:
    """Change summary from the run's denormalized (quarantine-excluded) counts."""
    return comment_markdown._format_change_counts(run.changed_count, run.new_count, run.removed_count)


# The count fields `_recount` assigns. A caller that publishes them alongside other
# fields passes these to its own `save(update_fields=...)`.
COUNT_FIELDS = ("changed_count", "new_count", "removed_count", "tolerated_match_count")


def _recount(run: Run) -> list[RunSnapshot]:
    """Re-stamp quarantine and recount the run's snapshots onto `run`, without saving.

    Counts on the run (changed_count, new_count, removed_count) reflect the raw
    classifier output excluding quarantined snapshots.

    The caller owns the write, because `finish_processing` must publish these counts
    in the same write as the completed status. Returns the loaded snapshots so the
    caller does not query them again.
    """
    _stamp_quarantine(run)

    snapshots = list(run.snapshots.using(WRITER_DB).select_related("tolerated_hash_match").all())

    run.changed_count = sum(1 for s in snapshots if s.result == SnapshotResult.CHANGED and not s.is_quarantined)
    run.new_count = sum(1 for s in snapshots if s.result == SnapshotResult.NEW and not s.is_quarantined)
    run.removed_count = sum(1 for s in snapshots if s.result == SnapshotResult.REMOVED and not s.is_quarantined)
    run.tolerated_match_count = sum(
        1
        for s in snapshots
        if s.tolerated_hash_match is not None and s.tolerated_hash_match.reason == ToleratedReason.HUMAN
    )
    return snapshots


def _post_status(run: Run, snapshots: list[RunSnapshot]) -> int:
    """Compute unresolved and post the commit status that gates CI.

    The unresolved count is separate from the run's counts because it further
    excludes tolerated and approved snapshots.

    Returns the unresolved count.
    """
    unresolved = sum(1 for s in snapshots if _is_unresolved(s))

    # Approved-but-uncommitted changes still block the gate: the baseline on the PR branch
    # doesn't reflect them yet, so re-running CI would re-detect them. Only finalize commits
    # the baseline (and posts success directly), so until then the gate must stay red.
    pending_commit = 0 if run.approved else len(baselines._approved_baseline_updates(snapshots))

    repo = run.repo
    if run.error_message:
        ci_status._post_commit_status(run, repo, "error", f"Visual review failed: {run.error_message[:100]}")
    elif run.purpose == RunPurpose.OBSERVE:
        # Default-branch (tracking-only) runs never gate — there's no PR to approve.
        # Report any changes as a green, informational status instead of a blocking
        # failure; the per-snapshot detail lives in the VR UI (linked via target_url).
        summary = _changes_summary(run)
        description = f"Tracking only: {summary} recorded" if summary else "Tracking only: no visual changes"
        ci_status._post_commit_status(run, repo, "success", description)
    elif unresolved > 0:
        ci_status._post_commit_status(run, repo, "failure", f"Visual changes detected: {_changes_summary(run)}")
        comments._post_review_prompt_comment(run, repo)
    elif pending_commit > 0:
        ci_status._post_commit_status(
            run,
            repo,
            "failure",
            f"{pending_commit} approved change(s) awaiting commit — finalize the run to update the baseline",
        )
    else:
        ci_status._post_commit_status(run, repo, "success", "No visual changes")

    return unresolved


def _update_counts_and_post_status(run: Run) -> int:
    """Recount the run, save the counts on their own, and post the commit status.

    For a run that is already completed, where the status is not part of the write.

    Returns the unresolved count.
    """
    snapshots = _recount(run)
    run.save(update_fields=COUNT_FIELDS)
    return _post_status(run, snapshots)
