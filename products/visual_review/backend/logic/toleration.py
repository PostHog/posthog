"""Tolerated hashes: accepting a known alternate rendering as not-a-regression."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from uuid import UUID

from django.db import transaction
from django.db.models import Count, Q
from django.utils import timezone

from ..db import WRITER_DB
from ..facade.enums import INTENTIONAL_TOLERATE_REASONS, ActorType, ReviewState, SnapshotResult, ToleratedReason
from ..models import Run, RunSnapshot, ToleratedHash
from . import errors, run_queries
from .run_queries import SnapshotKey


@transaction.atomic(using=WRITER_DB)
def mark_snapshot_as_tolerated(
    run_id: UUID, snapshot_id: UUID, user_id: int, team_id: int, actor: ActorType = ActorType.HUMAN
) -> RunSnapshot:
    """Mark a changed snapshot as a known tolerated alternate (a reviewer's decision).

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
    tolerated, created = ToleratedHash.objects.get_or_create(
        team_id=team_id,
        repo_id=run.repo_id,
        identifier=snapshot.identifier,
        baseline_hash=snapshot.baseline_hash,
        alternate_hash=snapshot.current_hash,
        defaults={
            "reason": ToleratedReason.AGENT if actor == ActorType.AGENT else ToleratedReason.HUMAN,
            "source_run": run,
            "created_by_id": user_id,
            "diff_percentage": snapshot.diff_percentage,
        },
    )

    # `complete_run` reads only rows whose expires_at is null or in the future, so an
    # expired row left alone makes this call a silent no-op: it reports success and the
    # next run flags the snapshot again. Revive it, and change nothing else. The row is
    # shared by every snapshot that matched this hash pair, and `reason` and `created_at`
    # describe runs that already happened: `flakiness._SOFT` counts a soft match only
    # while the row still says auto_threshold, and the baseline overview buckets a
    # toleration by its created_at. Rewriting either would edit that history. Today's
    # decision is recorded per snapshot below, which is where it belongs.
    if not created and tolerated.expires_at is not None:
        tolerated.expires_at = None
        tolerated.save(update_fields=["expires_at"])

    # result stays CHANGED — it's the technical truth (hashes differ).
    # review_state captures the human decision to tolerate.
    snapshot.review_state = ReviewState.TOLERATED
    snapshot.reviewed_at = timezone.now()
    snapshot.reviewed_by_id = user_id
    snapshot.tolerated_hash_match = tolerated
    snapshot.save(update_fields=["review_state", "reviewed_at", "reviewed_by_id", "tolerated_hash_match"])

    # Update tolerated_match_count (only decided tolerations, not auto-threshold)
    tolerated_count = (
        RunSnapshot.objects.using(WRITER_DB)
        .filter(
            run=run,
            tolerated_hash_match__isnull=False,
            tolerated_hash_match__reason__in=INTENTIONAL_TOLERATE_REASONS,
        )
        .count()
    )
    Run.objects.using(WRITER_DB).filter(id=run.id).update(tolerated_match_count=tolerated_count)

    return snapshot


def count_active_variants_against_current_baseline(
    repo_id: UUID, *, now: datetime, newest_run_by_type: Mapping[str, Run] | None = None
) -> dict[SnapshotKey, int]:
    """How many accepted variants each snapshot identity still carries against the baseline it
    would be compared against right now.

    A toleration is recorded under the baseline hash it was decided for, so a baseline change
    invalidates the whole pile at once and this count drops back to zero. That is what makes the
    number worth acting on: every row it counts is still in use.

    Counted with no recency cutoff, unlike the 30-day and 90-day counts on the baselines overview.
    Those measure how often somebody accepted drift; this measures how many accepted renderings the
    baseline is standing in for, and an accepted variant keeps matching without a new record.

    Keys carry the run type because the same identifier under two run types is two baselines.
    Only non-zero counts are returned.

    A caller that already holds the default-branch run universe passes it as `newest_run_by_type`,
    so the same page or digest run does not read it twice.
    """
    baseline_hash_by_key = _current_baseline_hashes(repo_id, newest_run_by_type)
    if not baseline_hash_by_key:
        return {}

    live = Q(expires_at__isnull=True) | Q(expires_at__gt=now)
    # The exact pair is still matched below, because two identifiers can share a baseline hash.
    counts_by_pair = {
        (identifier, baseline_hash): count
        for identifier, baseline_hash, count in ToleratedHash.objects.filter(
            repo_id=repo_id,
            identifier__in=list({key.identifier for key in baseline_hash_by_key}),
            baseline_hash__in=list(set(baseline_hash_by_key.values())),
            reason__in=INTENTIONAL_TOLERATE_REASONS,
        )
        .filter(live)
        .values_list("identifier", "baseline_hash")
        .annotate(c=Count("id"))
        .values_list("identifier", "baseline_hash", "c")
    }
    counts: dict[SnapshotKey, int] = {}
    for key, baseline_hash in baseline_hash_by_key.items():
        count = counts_by_pair.get((key.identifier, baseline_hash), 0)
        if count:
            counts[key] = count
    return counts


def _current_baseline_hashes(
    repo_id: UUID, newest_run_by_type: Mapping[str, Run] | None = None
) -> dict[SnapshotKey, str]:
    """The baseline hash each snapshot identity would be compared against right now.

    values_list rather than model hydration: the universe runs to thousands of rows and nothing
    here needs anything else off them.
    """
    if newest_run_by_type is None:
        newest_run_by_type = run_queries.newest_run_by_run_type(run_queries.latest_default_branch_runs(repo_id))
    run_type_by_run_id = {run.id: run_type for run_type, run in newest_run_by_type.items()}
    if not run_type_by_run_id:
        return {}
    return {
        SnapshotKey(run_type=run_type_by_run_id[run_id], identifier=identifier): baseline_hash
        for run_id, identifier, baseline_hash in RunSnapshot.objects.filter(
            run_id__in=list(run_type_by_run_id)
        ).values_list("run_id", "identifier", "baseline_hash")
        # A snapshot with no baseline yet has nothing for a toleration to be recorded against, and
        # an empty hash would otherwise match every other baseline-less identity's rows.
        if baseline_hash
    }


def get_tolerated_hashes_for_identifier(repo_id: UUID, identifier: str) -> list[ToleratedHash]:
    """List all tolerated hashes for a snapshot identifier, most recent first."""
    return list(ToleratedHash.objects.filter(repo_id=repo_id, identifier=identifier).order_by("-created_at"))
