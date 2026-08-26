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
from ..facade.enums import ClassificationReason, RunStatus, SnapshotResult, ToleratedReason
from ..models import QuarantinedIdentifier, Run, RunSnapshot, ToleratedHash
from . import run_queries


@frozen
class _SnapshotKey:
    """One snapshot identity. The same identifier under two run types is two."""

    run_type: str
    identifier: str


@frozen
class _FlakeKey:
    """One snapshot identity's activity during one baseline, per run type.

    Matching ignores run type, because the classifier looks a tolerated row up
    by identifier and hashes alone. A row on this page does not: a recent
    Storybook flake says nothing about the Playwright row.
    """

    run_type: str
    identifier: str
    baseline_hash: str


@frozen
class _VariantKey:
    """One snapshot's variants, scoped to the baseline they were recorded against.

    No run type: `ToleratedHash` does not carry one, and the classifier looks
    rows up by identifier and baseline hash alone.
    """

    identifier: str
    baseline_hash: str


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
      `last_flaked_at` decides `unstable` against `settled`. That timestamp
      comes from the runs that matched a variant, not from when the variant was
      first recorded, because a snapshot can cycle through variants it already
      recorded without ever minting a new row.

    Population:
      Only identifiers with at least one live variant against their current
      baseline, or an active quarantine. Everything else has nothing to show,
      which keeps this an order of magnitude smaller than the baselines
      universe and removes any need to paginate.

    Query shape:
      - 1 query for the universe runs (one row per run_type, indexed)
      - 1 values-only query for the current baseline hash per identifier
      - 1 grouped query for variant count and mean diff
      - 1 grouped query for the per-day strip, bounded to the strip window
      - 1 query for active quarantines
      - 1 grouped query for when each baseline era started and last flaked,
        scanned only for identifiers that can produce a row
      - 1 query to hydrate thumbnails, for listed rows only
    """
    now = timezone.now()
    today = now.date()

    live = Q(expires_at__isnull=True) | Q(expires_at__gt=now)

    # Every active quarantine in the repo, not only the ones whose snapshot has
    # a baseline. Quarantining does not require one, and the empty state
    # promises that quarantining alone puts a snapshot on this page. The set is
    # small by nature, so no identifier filter is needed to bound it.
    #
    # Hydrated so each row can render reason, expiry, who and the source run
    # without a per-row fetch. `Run.metadata` and `Run.error_message` can be
    # large and are not needed for the summary.
    active_quarantines_by_key: dict[_SnapshotKey, QuarantinedIdentifier] = {}
    for active_quarantine in (
        QuarantinedIdentifier.objects.filter(repo_id=repo_id)
        .filter(live)
        .select_related("source_run")
        .defer("source_run__metadata", "source_run__error_message")
        .order_by("-created_at")
    ):
        quarantine_key = _SnapshotKey(run_type=active_quarantine.run_type, identifier=active_quarantine.identifier)
        # Creating a quarantine supersedes the prior active row, so duplicates
        # should not exist. Keep the newest if one ever does.
        if quarantine_key not in active_quarantines_by_key:
            active_quarantines_by_key[quarantine_key] = active_quarantine

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
        .only("id", "run_type", "created_at")
    )
    if not universe_runs:
        return _quarantine_only_raw(
            active_quarantines_by_key,
            generated_at=now,
            strip_days=FLAKINESS_STRIP_DAYS,
            max_entries=FLAKINESS_MAX_ENTRIES,
        )

    # `universe_runs` holds one run per branch and run type, so a repo with runs
    # on both master and main has two per run type. The row identity carries no
    # branch, so keep only the newest run per run type. Otherwise whichever
    # branch happened to be read last decided the baseline, and two identical
    # requests could disagree.
    newest_run_by_type: dict[str, Run] = {}
    for run in sorted(universe_runs, key=lambda r: r.created_at, reverse=True):
        newest_run_by_type.setdefault(run.run_type, run)

    run_type_by_run_id = {run.id: run_type for run_type, run in newest_run_by_type.items()}
    universe_run_ids = list(run_type_by_run_id)

    # The baseline hash each identifier would be compared against right now.
    # values_list rather than model hydration: the universe can run to
    # thousands of rows and only the listed ones need thumbnails later.
    baseline_hash_by_key: dict[_SnapshotKey, str] = {}
    for run_id, identifier, baseline_hash in RunSnapshot.objects.filter(run_id__in=universe_run_ids).values_list(
        "run_id", "identifier", "baseline_hash"
    ):
        if baseline_hash:
            baseline_hash_by_key[_SnapshotKey(run_type=run_type_by_run_id[run_id], identifier=identifier)] = (
                baseline_hash
            )

    # One entry per `(run_type, identifier)` that has a baseline to compare
    # against. Not a row count: rows carry snapshots with no baseline yet, and
    # repeat an identity when a repo runs on both master and main.
    tracked_total = len(baseline_hash_by_key)

    universe_identifiers = list({key.identifier for key in baseline_hash_by_key})
    universe_baseline_hashes = list(set(baseline_hash_by_key.values()))

    # Only rows the classifier could still match: auto-minted, and live.
    # Mirrors the `expires_at` filter in `runs.complete_run` so this count
    # equals what a run would actually match.
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
    variants_by_pair: dict[_VariantKey, _VariantStats] = {}
    for identifier, baseline_hash, variant_count, avg_diff in (
        auto_tolerations.values("identifier", "baseline_hash")
        .annotate(
            variant_count=Count("alternate_hash", distinct=True),
            avg_diff=Avg("diff_percentage"),
        )
        .values_list("identifier", "baseline_hash", "variant_count", "avg_diff")
    ):
        variants_by_pair[_VariantKey(identifier=identifier, baseline_hash=baseline_hash)] = _VariantStats(
            count=variant_count,
            avg_diff_percentage=avg_diff,
        )

    # Per-day counts for the activity strip. `(identifier, baseline_hash,
    # alternate_hash)` is unique, so a row is a distinct variant and a plain
    # count per day needs no DISTINCT.
    strip_start = today - timedelta(days=FLAKINESS_STRIP_DAYS - 1)
    daily_by_pair: dict[_VariantKey, dict[date, int]] = defaultdict(dict)
    for identifier, baseline_hash, day, count in (
        auto_tolerations.filter(created_at__date__gte=strip_start)
        .annotate(day=TruncDate("created_at"))
        .values("identifier", "baseline_hash", "day")
        .annotate(day_count=Count("id"))
        .values_list("identifier", "baseline_hash", "day", "day_count")
    ):
        daily_by_pair[_VariantKey(identifier=identifier, baseline_hash=baseline_hash)][day] = count

    # Only identifiers that can produce a row. Everything else is dropped by the
    # assembly loop below, so scanning it buys nothing.
    reportable_identifiers = list(
        {key.identifier for key in variants_by_pair} | {key.identifier for key in active_quarantines_by_key}
    )
    if not reportable_identifiers:
        return _FlakinessRaw.empty(generated_at=now, tracked_total=tracked_total)

    # When each baseline last moved. A real flip on the default branch leaves a
    # CHANGED or REMOVED row in the run that introduced it, because later runs
    # compare against the new committed baseline and see UNCHANGED. That makes
    # `Max` the most recent flip, which stays right when a baseline is reverted
    # to a hash it held before.
    #
    # CHANGED is not only a flip. A snapshot that keeps rendering differently
    # from an unchanged baseline, with no toleration to match it, records
    # CHANGED on every run. `Max` then reports the latest failure instead of the
    # last real move, so the age reads too new for that snapshot.
    #
    # Grouping the whole history by `baseline_hash` instead would read more
    # precisely, but it admits every historical row rather than the rare event
    # rows, which is the shape `baseline_overview` documents as ~7s and an OOM
    # on the web pod. This uses the `snapshot_run_result` index the same way its
    # neighbour does.
    baseline_moved_at_by_key: dict[_SnapshotKey, datetime] = {}
    for identifier, run_type, moved_at in (
        RunSnapshot.objects.filter(
            run__repo_id=repo_id,
            run__branch__in=run_queries._DEFAULT_BRANCHES,
            run__status=RunStatus.COMPLETED,
            result__in=(SnapshotResult.CHANGED, SnapshotResult.REMOVED),
            identifier__in=reportable_identifiers,
        )
        .values("identifier", "run__run_type")
        .annotate(moved_at=Max("run__created_at"))
        .values_list("identifier", "run__run_type", "moved_at")
    ):
        if moved_at is not None:
            baseline_moved_at_by_key[_SnapshotKey(run_type=run_type, identifier=identifier)] = moved_at

    minted_recently_by_key: dict[_FlakeKey, datetime] = {}
    for run_type, identifier, baseline_hash, minted_at in (
        auto_tolerations.filter(
            source_run__branch__in=run_queries._DEFAULT_BRANCHES,
            source_run__status=RunStatus.COMPLETED,
        )
        .values("source_run__run_type", "identifier", "baseline_hash")
        # The run's timestamp, not the row's. `created_at` is when the toleration
        # was written, which can lag or be retried, and the repeat-match half
        # already reports when the run happened.
        .annotate(minted_at=Max("source_run__created_at"))
        .values_list("source_run__run_type", "identifier", "baseline_hash", "minted_at")
    ):
        if minted_at is not None:
            minted_recently_by_key[_FlakeKey(run_type=run_type, identifier=identifier, baseline_hash=baseline_hash)] = (
                minted_at
            )

    # When each snapshot last rendered one of its variants, from the runs that
    # matched. Bounded to the recency window on purpose: this decides `unstable`
    # against `settled`, and that decision only looks that far back. Beyond the
    # window the mint time below is the answer, and it is older or equal, which
    # keeps the state correct.
    #
    # The mint time alone is not enough, because `diffing.py` mints with
    # `get_or_create` and the classifier only links the matching `RunSnapshot`
    # back to the row. A snapshot cycling through variants it already recorded
    # never refreshes `created_at`, so it would read as settled while it still
    # fails to render the same way twice.
    live_match = Q(tolerated_hash_match__expires_at__isnull=True) | Q(tolerated_hash_match__expires_at__gt=now)
    matched_recently_by_key: dict[_FlakeKey, datetime] = {}
    for run_type, identifier, baseline_hash, matched_at in (
        RunSnapshot.objects.filter(
            run__repo_id=repo_id,
            run__branch__in=run_queries._DEFAULT_BRANCHES,
            run__status=RunStatus.COMPLETED,
            run__created_at__gte=now - timedelta(days=FLAKINESS_RECENT_DAYS),
            identifier__in=reportable_identifiers,
            classification_reason=ClassificationReason.TOLERATED_HASH,
            tolerated_hash_match__reason=ToleratedReason.AUTO_THRESHOLD,
        )
        .filter(live_match)
        .values("run__run_type", "identifier", "baseline_hash")
        .annotate(matched_at=Max("run__created_at"))
        .values_list("run__run_type", "identifier", "baseline_hash", "matched_at")
    ):
        if matched_at is not None:
            matched_recently_by_key[
                _FlakeKey(run_type=run_type, identifier=identifier, baseline_hash=baseline_hash)
            ] = matched_at

    recency_cutoff = now - timedelta(days=FLAKINESS_RECENT_DAYS)
    expiry_soon_cutoff = now + timedelta(days=FLAKINESS_EXPIRY_SOON_DAYS)

    # A quarantine can cover a snapshot that has no current baseline: one added
    # in this run, or one that dropped out of the latest default-branch run.
    # Those keys are absent from `baseline_hash_by_key`, so walk them too rather
    # than hide a quarantine somebody is relying on.
    quarantine_only_keys = active_quarantines_by_key.keys() - baseline_hash_by_key.keys()
    scored_keys: list[tuple[_SnapshotKey, str]] = [
        *baseline_hash_by_key.items(),
        *((key, "") for key in quarantine_only_keys),
    ]

    rows: list[_FlakinessRow] = []
    for key, baseline_hash in scored_keys:
        variant_key = _VariantKey(identifier=key.identifier, baseline_hash=baseline_hash)
        stats = variants_by_pair.get(variant_key) if baseline_hash else None
        quarantine = active_quarantines_by_key.get(key)
        if stats is None and quarantine is None:
            continue

        flake_key = _FlakeKey(run_type=key.run_type, identifier=key.identifier, baseline_hash=baseline_hash)
        variant_count = stats.count if stats is not None else 0
        last_flaked_at = _latest(
            minted_recently_by_key.get(flake_key),
            matched_recently_by_key.get(flake_key),
        )
        is_unstable = last_flaked_at is not None and last_flaked_at >= recency_cutoff
        rows.append(
            _FlakinessRow(
                run_type=key.run_type,
                identifier=key.identifier,
                variant_count=variant_count,
                last_flaked_at=last_flaked_at,
                avg_diff_percentage=stats.avg_diff_percentage if stats is not None else None,
                daily_counts=_daily_series(
                    daily_by_pair.get(variant_key, {}),
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

    # Ordering decides what survives the cap, so the rows somebody has to act on
    # come first. Sorting on variant count alone put clean quarantines last,
    # exactly the rows the `quarantined` and `needs a decision` filters exist to
    # surface, and the tiles would still have counted them.
    #
    # Rows that never flaked sort last within their group against an aware
    # epoch, because `last_flaked_at` is aware and mixing it with a naive
    # datetime raises.
    never = datetime.min.replace(tzinfo=UTC)
    rows.sort(
        key=lambda row: (
            row.needs_decision,
            row.quarantine is not None,
            row.variant_count,
            row.last_flaked_at or never,
        ),
        reverse=True,
    )
    listed = rows[:FLAKINESS_MAX_ENTRIES]

    snapshots_by_key = _hydrate_snapshots(
        universe_run_ids=universe_run_ids,
        run_type_by_run_id=run_type_by_run_id,
        keys={_SnapshotKey(run_type=row.run_type, identifier=row.identifier) for row in listed},
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


def _quarantine_only_raw(
    active_quarantines_by_key: dict[_SnapshotKey, QuarantinedIdentifier],
    *,
    generated_at: datetime,
    strip_days: int,
    max_entries: int,
) -> _FlakinessRaw:
    """The page for a repo with no completed default-branch run yet.

    There is no baseline to score against, so `tracked` is 0 and every row is
    clean. The quarantines still have to appear: creating one does not require
    a baseline, and someone is relying on the snapshot being skipped.
    """
    rows = [
        _FlakinessRow(
            run_type=key.run_type,
            identifier=key.identifier,
            variant_count=0,
            last_flaked_at=None,
            avg_diff_percentage=None,
            daily_counts=[0] * strip_days,
            baseline_moved_at=None,
            is_unstable=False,
            quarantine=quarantine,
            needs_decision=True,
        )
        for key, quarantine in active_quarantines_by_key.items()
    ]
    rows.sort(key=lambda row: (row.run_type, row.identifier))
    listed = rows[:max_entries]
    return _FlakinessRaw(
        rows=listed,
        snapshots_by_key={},
        tracked_total=0,
        totals_unstable=0,
        totals_settled=0,
        # Totals count the whole population, as they do on the normal path, so
        # the tiles stay right when the list is capped.
        totals_quarantined=len(rows),
        totals_needs_decision=len(rows),
        by_run_type=dict(Counter(row.run_type for row in rows)),
        truncated=len(listed) < len(rows),
        generated_at=generated_at,
    )


def _latest(*moments: datetime | None) -> datetime | None:
    """The most recent of several optional timestamps, or None when all are unset."""
    known = [moment for moment in moments if moment is not None]
    return max(known) if known else None


def snapshot_key(row: _FlakinessRow) -> _SnapshotKey:
    """Key for `_FlakinessRaw.snapshots_by_key`, for the facade to look a row up."""
    return _SnapshotKey(run_type=row.run_type, identifier=row.identifier)


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
    keys: set[_SnapshotKey],
) -> dict[_SnapshotKey, RunSnapshot]:
    """Thumbnail and dimension data for the listed rows only."""
    if not keys:
        return {}
    identifiers = list({key.identifier for key in keys})
    hydrated: dict[_SnapshotKey, RunSnapshot] = {}
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
        key = _SnapshotKey(run_type=run_type_by_run_id[snapshot.run_id], identifier=snapshot.identifier)
        if key in keys:
            hydrated[key] = snapshot
    return hydrated


@frozen
class _VariantStats:
    """Grouped toleration stats for one `(identifier, baseline_hash)` pair."""

    count: int
    avg_diff_percentage: float | None


@frozen
class _FlakinessRow:
    """One scored snapshot identity, before thumbnails and users are attached."""

    run_type: str
    identifier: str
    variant_count: int
    last_flaked_at: datetime | None
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
    snapshots_by_key: dict[_SnapshotKey, RunSnapshot]
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
