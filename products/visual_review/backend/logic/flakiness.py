"""The flakiness aggregate that backs the flakiness scene.

Scores each snapshot identity on the alternate hashes the classifier can still
match for it. See `get_flakiness_overview` for why that is scoped to the
current baseline rather than to a rolling time window.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from django.db.models import Avg, Count, Max, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from posthog.dataclasses import frozen

from ..facade.contracts import (
    FLAKINESS_EXPIRY_SOON_DAYS,
    FLAKINESS_MAX_ENTRIES,
    FLAKINESS_RECENT_DAYS,
    FLAKINESS_STRIP_DAYS,
)
from ..facade.enums import RunStatus, SnapshotResult, ToleratedReason
from ..models import QuarantinedIdentifier, Run, RunSnapshot, ToleratedHash
from . import run_queries


def get_flakiness_overview(repo_id: UUID) -> _FlakinessRaw:
    """Snapshot identities that carry rendering instability or a quarantine.

    Scope, and why it is not a rolling window:
      A `ToleratedHash` row is stored against a specific `baseline_hash`, and
      the classifier only matches a row whose baseline hash is still the
      baseline (see `SnapshotClassifier.classify_remaining`). So the moment a
      snapshot genuinely changes and its baseline moves, every variant recorded
      before that becomes unreachable forever. Counting those would report
      churn from a version of the snapshot that no longer exists. Scoping to
      the current baseline instead gives a window that resets exactly when the
      snapshot changed, and it is served by the existing `tolerated_lookup`
      index on `(repo, identifier, baseline_hash)` without a new one.

      Baseline scoping alone is not enough. A snapshot that someone made
      deterministic without moving its baseline keeps its variant count, so
      `last_variant_at` decides `unstable` against `settled`.

    Population:
      Only identifiers with at least one live variant against their current
      baseline, or an active quarantine. Everything else has nothing to show,
      which keeps this an order of magnitude smaller than the baselines
      universe and removes any need to paginate.

    Query shape:
      - 1 query for the universe runs (one row per run_type, indexed)
      - 1 values-only query for the current baseline hash per identifier
      - 1 grouped query for variant count, last variant and mean diff
      - 1 grouped query for the per-day strip, bounded to the strip window
      - 1 grouped query for the last baseline move per identifier
      - 1 query for active quarantines
      - 1 query to hydrate thumbnails, for listed rows only
    """
    now = timezone.now()
    today = now.date()

    # `status=completed` rather than `superseded_by IS NULL`: a freshly started
    # run on the default branch is un-superseded but has few or no RunSnapshots
    # ingested yet, which would collapse the universe to whatever it has loaded
    # so far. Same reasoning as `baseline_overview.get_baselines_overview`.
    universe_runs = list(
        Run.objects.filter(
            repo_id=repo_id,
            branch__in=run_queries._DEFAULT_BRANCHES,
            status=RunStatus.COMPLETED,
        )
        .order_by("repo_id", "branch", "run_type", "-created_at")
        .distinct("repo_id", "branch", "run_type")
        .only("id", "run_type")
    )
    if not universe_runs:
        return _FlakinessRaw.empty(generated_at=now)

    run_type_by_run_id = {run.id: run.run_type for run in universe_runs}
    universe_run_ids = list(run_type_by_run_id)

    # The baseline hash each identifier would be compared against right now.
    # values_list rather than model hydration: the universe can run to
    # thousands of rows and only the listed ones need thumbnails later.
    baseline_hash_by_key: dict[tuple[str, str], str] = {}
    tracked_total = 0
    for run_id, identifier, baseline_hash in RunSnapshot.objects.filter(run_id__in=universe_run_ids).values_list(
        "run_id", "identifier", "baseline_hash"
    ):
        tracked_total += 1
        if baseline_hash:
            baseline_hash_by_key[(run_type_by_run_id[run_id], identifier)] = baseline_hash

    if not baseline_hash_by_key:
        return _FlakinessRaw.empty(generated_at=now, tracked_total=tracked_total)

    universe_identifiers = list({identifier for _, identifier in baseline_hash_by_key})
    universe_baseline_hashes = list(set(baseline_hash_by_key.values()))

    # Only rows the classifier could still match: auto-minted, and live.
    # Mirrors the `expires_at` filter in `runs.complete_run` so this count
    # equals what a run would actually match.
    live = Q(expires_at__isnull=True) | Q(expires_at__gt=now)
    auto_tolerations = ToleratedHash.objects.filter(
        repo_id=repo_id,
        reason=ToleratedReason.AUTO_THRESHOLD,
        identifier__in=universe_identifiers,
        baseline_hash__in=universe_baseline_hashes,
    ).filter(live)

    # Both `__in` filters narrow on the `tolerated_lookup` index, but they are
    # independent, so a row could match one identifier's baseline hash under
    # another identifier's name. Content hashes make that vanishingly unlikely,
    # and the exact pair is verified when entries are assembled below.
    variants_by_pair: dict[tuple[str, str], _VariantStats] = {}
    for identifier, baseline_hash, variant_count, last_variant_at, avg_diff in (
        auto_tolerations.values("identifier", "baseline_hash")
        .annotate(
            variant_count=Count("alternate_hash", distinct=True),
            last_variant_at=Max("created_at"),
            avg_diff=Avg("diff_percentage"),
        )
        .values_list("identifier", "baseline_hash", "variant_count", "last_variant_at", "avg_diff")
    ):
        variants_by_pair[(identifier, baseline_hash)] = _VariantStats(
            count=variant_count,
            last_at=last_variant_at,
            avg_diff_percentage=avg_diff,
        )

    # Per-day counts for the activity strip. `(identifier, baseline_hash,
    # alternate_hash)` is unique, so a row is a distinct variant and a plain
    # count per day needs no DISTINCT.
    strip_start = today - timedelta(days=FLAKINESS_STRIP_DAYS - 1)
    daily_by_pair: dict[tuple[str, str], dict[date, int]] = defaultdict(dict)
    for identifier, baseline_hash, day, count in (
        auto_tolerations.filter(created_at__date__gte=strip_start)
        .annotate(day=TruncDate("created_at"))
        .values("identifier", "baseline_hash", "day")
        .annotate(day_count=Count("id"))
        .values_list("identifier", "baseline_hash", "day", "day_count")
    ):
        daily_by_pair[(identifier, baseline_hash)][day] = count

    # When each identifier's baseline last moved. A real baseline flip leaves a
    # CHANGED or REMOVED row in the run that introduced it, because later runs
    # compare against the new committed baseline and see UNCHANGED. Adds one
    # aggregate to the query shape `baseline_overview` already runs, on the
    # same `snapshot_run_result` index.
    baseline_moved_at_by_key: dict[tuple[str, str], datetime] = {}
    for identifier, run_type, moved_at in (
        RunSnapshot.objects.filter(
            run__repo_id=repo_id,
            run__branch__in=run_queries._DEFAULT_BRANCHES,
            run__status=RunStatus.COMPLETED,
            result__in=(SnapshotResult.CHANGED, SnapshotResult.REMOVED),
            identifier__in=universe_identifiers,
        )
        .values("identifier", "run__run_type")
        .annotate(moved_at=Max("run__created_at"))
        .values_list("identifier", "run__run_type", "moved_at")
    ):
        if moved_at is not None:
            baseline_moved_at_by_key[(run_type, identifier)] = moved_at

    # Hydrated so each row can render reason, expiry, who and the source run
    # without a per-row fetch. `Run.metadata` and `Run.error_message` can be
    # large and are not needed for the summary.
    active_quarantines_by_key: dict[tuple[str, str], QuarantinedIdentifier] = {}
    for active_quarantine in (
        QuarantinedIdentifier.objects.filter(repo_id=repo_id, identifier__in=universe_identifiers)
        .filter(live)
        .select_related("source_run")
        .defer("source_run__metadata", "source_run__error_message")
        .order_by("-created_at")
    ):
        quarantine_key = (active_quarantine.run_type, active_quarantine.identifier)
        # Creating a quarantine supersedes the prior active row, so duplicates
        # should not exist. Keep the newest if one ever does.
        if quarantine_key not in active_quarantines_by_key:
            active_quarantines_by_key[quarantine_key] = active_quarantine

    recency_cutoff = now - timedelta(days=FLAKINESS_RECENT_DAYS)
    expiry_soon_cutoff = now + timedelta(days=FLAKINESS_EXPIRY_SOON_DAYS)

    rows: list[_FlakinessRow] = []
    for key, baseline_hash in baseline_hash_by_key.items():
        run_type, identifier = key
        stats = variants_by_pair.get((identifier, baseline_hash))
        quarantine = active_quarantines_by_key.get(key)
        if stats is None and quarantine is None:
            continue

        variant_count = stats.count if stats is not None else 0
        last_variant_at = stats.last_at if stats is not None else None
        is_unstable = last_variant_at is not None and last_variant_at >= recency_cutoff
        rows.append(
            _FlakinessRow(
                run_type=run_type,
                identifier=identifier,
                variant_count=variant_count,
                last_variant_at=last_variant_at,
                avg_diff_percentage=stats.avg_diff_percentage if stats is not None else None,
                daily_counts=_daily_series(
                    daily_by_pair.get((identifier, baseline_hash), {}),
                    strip_start=strip_start,
                    length=FLAKINESS_STRIP_DAYS,
                ),
                baseline_moved_at=baseline_moved_at_by_key.get(key),
                is_unstable=is_unstable,
                quarantine=quarantine,
                needs_decision=_needs_decision(
                    quarantine=quarantine,
                    variant_count=variant_count,
                    expiry_soon_cutoff=expiry_soon_cutoff,
                ),
            )
        )

    # Most variants first, then most recently active, so the worst offenders
    # lead regardless of which the client sorts by afterwards. Rows with no
    # variants sort last against an aware epoch, because `last_variant_at` is
    # aware and mixing it with a naive datetime raises.
    never = datetime.min.replace(tzinfo=UTC)
    rows.sort(key=lambda row: (row.variant_count, row.last_variant_at or never), reverse=True)
    listed = rows[:FLAKINESS_MAX_ENTRIES]

    snapshots_by_key = _hydrate_snapshots(
        universe_run_ids=universe_run_ids,
        run_type_by_run_id=run_type_by_run_id,
        keys={(row.run_type, row.identifier) for row in listed},
    )

    return _FlakinessRaw(
        rows=listed,
        snapshots_by_key=snapshots_by_key,
        tracked_total=tracked_total,
        totals_unstable=sum(1 for row in rows if row.is_unstable),
        totals_settled=sum(1 for row in rows if not row.is_unstable and row.variant_count > 0),
        totals_quarantined=sum(1 for row in rows if row.quarantine is not None),
        totals_needs_decision=sum(1 for row in rows if row.needs_decision),
        by_run_type=dict(Counter(row.run_type for row in rows)),
        truncated=len(listed) < len(rows),
        generated_at=now,
    )


def _needs_decision(
    *,
    quarantine: QuarantinedIdentifier | None,
    variant_count: int,
    expiry_soon_cutoff: datetime,
) -> bool:
    """Whether an active quarantine has stopped matching what it was opened for.

    Three ways that happens: it already ran out, it is about to, or the
    snapshot it covers no longer produces variants at all. An expired entry is
    not in `quarantine` to begin with, because the caller filters on
    `expires_at`, so only the last two are testable here.
    """
    if quarantine is None:
        return False
    if variant_count == 0:
        return True
    return quarantine.expires_at is not None and quarantine.expires_at <= expiry_soon_cutoff


def _daily_series(counts_by_day: dict[date, int], *, strip_start: date, length: int) -> list[int]:
    """Dense oldest-first series so the frontend renders a fixed axis."""
    return [counts_by_day.get(strip_start + timedelta(days=offset), 0) for offset in range(length)]


def _hydrate_snapshots(
    *,
    universe_run_ids: list[UUID],
    run_type_by_run_id: dict[UUID, str],
    keys: set[tuple[str, str]],
) -> dict[tuple[str, str], RunSnapshot]:
    """Thumbnail and dimension data for the listed rows only."""
    if not keys:
        return {}
    identifiers = list({identifier for _, identifier in keys})
    hydrated: dict[tuple[str, str], RunSnapshot] = {}
    for snapshot in (
        RunSnapshot.objects.filter(run_id__in=universe_run_ids, identifier__in=identifiers)
        .select_related("current_artifact__thumbnail")
        .only(
            "identifier",
            "metadata",
            "run_id",
            "current_artifact__width",
            "current_artifact__height",
            "current_artifact__thumbnail__content_hash",
        )
    ):
        key = (run_type_by_run_id[snapshot.run_id], snapshot.identifier)
        if key in keys:
            hydrated[key] = snapshot
    return hydrated


@frozen
class _VariantStats:
    """Grouped toleration stats for one `(identifier, baseline_hash)` pair."""

    count: int
    last_at: datetime | None
    avg_diff_percentage: float | None


@frozen
class _FlakinessRow:
    """One scored snapshot identity, before thumbnails and users are attached."""

    run_type: str
    identifier: str
    variant_count: int
    last_variant_at: datetime | None
    avg_diff_percentage: float | None
    daily_counts: list[int]
    baseline_moved_at: datetime | None
    is_unstable: bool
    quarantine: QuarantinedIdentifier | None
    needs_decision: bool


@frozen
class _FlakinessRaw:
    """Internal raw shape. The facade reshapes this into the public DTOs.

    Private to this package so contract changes do not ripple back in.
    """

    rows: list[_FlakinessRow]
    snapshots_by_key: dict[tuple[str, str], RunSnapshot]
    tracked_total: int
    totals_unstable: int
    totals_settled: int
    totals_quarantined: int
    totals_needs_decision: int
    by_run_type: dict[str, int]
    truncated: bool
    generated_at: datetime

    @classmethod
    def empty(cls, *, generated_at: datetime, tracked_total: int = 0) -> _FlakinessRaw:
        return cls(
            rows=[],
            snapshots_by_key={},
            tracked_total=tracked_total,
            totals_unstable=0,
            totals_settled=0,
            totals_quarantined=0,
            totals_needs_decision=0,
            by_run_type={},
            truncated=False,
            generated_at=generated_at,
        )
