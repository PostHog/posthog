"""Tolerated hashes: accepting a known alternate rendering as not-a-regression."""

from __future__ import annotations

from uuid import UUID

from django.db import transaction
from django.utils import timezone

from ..db import WRITER_DB
from ..facade.enums import ReviewState, SnapshotResult, ToleratedReason
from ..models import Run, RunSnapshot, ToleratedHash
from . import errors, run_queries


@transaction.atomic(using=WRITER_DB)
def mark_snapshot_as_tolerated(run_id: UUID, snapshot_id: UUID, user_id: int, team_id: int) -> RunSnapshot:
    """Mark a changed snapshot as a known tolerated alternate (human decision).

    Creates a ToleratedHash entry tied to the current baseline, reclassifies the
    snapshot as UNCHANGED, and recalculates run summary counts.
    """
    run = run_queries._get_run_for_update(run_id, team_id=team_id)
    try:
        snapshot = RunSnapshot.objects.get(id=snapshot_id, run=run, team_id=team_id)
    except RunSnapshot.DoesNotExist:
        raise errors.RunNotFoundError(f"Snapshot {snapshot_id} not found in run {run_id}")

    if snapshot.result != SnapshotResult.CHANGED:
        raise ValueError(f"Can only mark CHANGED snapshots as tolerated (current: {snapshot.result})")

    if not snapshot.current_hash:
        raise ValueError("Snapshot has no current hash")

    # Explicit team_id in the lookup (not just defaults) so the IDOR audit
    # rule sees the scope; ProductTeamManager also auto-filters by canonical
    # team — both belt and suspenders.
    tolerated, _ = ToleratedHash.objects.get_or_create(
        team_id=team_id,
        repo_id=run.repo_id,
        identifier=snapshot.identifier,
        baseline_hash=snapshot.baseline_hash,
        alternate_hash=snapshot.current_hash,
        defaults={
            "reason": ToleratedReason.HUMAN,
            "source_run": run,
            "created_by_id": user_id,
            "diff_percentage": snapshot.diff_percentage,
        },
    )

    # result stays CHANGED — it's the technical truth (hashes differ).
    # review_state captures the human decision to tolerate.
    snapshot.review_state = ReviewState.TOLERATED
    snapshot.reviewed_at = timezone.now()
    snapshot.reviewed_by_id = user_id
    snapshot.tolerated_hash_match = tolerated
    snapshot.save(update_fields=["review_state", "reviewed_at", "reviewed_by_id", "tolerated_hash_match"])

    # Update tolerated_match_count (only human-tolerated, not auto-threshold)
    tolerated_count = (
        RunSnapshot.objects.using(WRITER_DB)
        .filter(run=run, tolerated_hash_match__isnull=False, tolerated_hash_match__reason=ToleratedReason.HUMAN)
        .count()
    )
    Run.objects.using(WRITER_DB).filter(id=run.id).update(tolerated_match_count=tolerated_count)

    return snapshot


def get_tolerated_hashes_for_identifier(repo_id: UUID, identifier: str) -> list[ToleratedHash]:
    """List all tolerated hashes for a snapshot identifier, most recent first."""
    return list(ToleratedHash.objects.filter(repo_id=repo_id, identifier=identifier).order_by("-created_at"))
