"""The flakiness aggregate that backs the flakiness scene.

Scores each snapshot identity on how often the default branch rendered it
differently from its baseline, and on how much of the diff threshold the
absorbed renders leave free. See `get_flakiness_overview` for the scoping rule
and the query shape.
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
    FLAKINESS_BROKEN_RATE,
    FLAKINESS_EXPIRY_SOON_DAYS,
    FLAKINESS_MAX_ENTRIES,
    FLAKINESS_MIN_HEADROOM,
    FLAKINESS_MIN_WINDOW_RUNS,
    FLAKINESS_RATE_DAYS,
    FLAKINESS_WINDOW_DAYS,
    PIXEL_DIFF_THRESHOLD_PERCENT,
)
from ..facade.enums import ClassificationReason, FlakinessState, ReviewState, RunStatus, SnapshotResult, ToleratedReason
from ..models import QuarantinedIdentifier, Run, RunSnapshot, ToleratedHash
from . import run_queries

# Rows a run recorded as a difference from the baseline, split by what that
# difference cost. `_HARD` failed the gate and blocked whoever was merging.
# `_SOFT` was absorbed: either it matched a toleration, or it was diffed this
# run and came in under both thresholds.
#
# The split matters because only one of them is a promise. A snapshot that is
# always absorbed is not stable, it is under a line, and it stays under only
# while its diff does. `headroom` below measures how much of that line is left.
#
# `_HARD` is every result that is not UNCHANGED, which is what `gating.
# _is_unresolved` gates on. CHANGED alone would miss the two quieter ways a
# snapshot fails: NEW, when its baseline was never committed or was dropped
# from the file, and REMOVED, when the baseline outlived the story. Both fail
# every run until somebody acts, and a quarantine hides them exactly as it
# hides a CHANGED one.
#
# Mirrors `gating._is_unresolved`: a result other than `unchanged` that nobody
# has signed off. PostHog's own default-branch runs are `RunPurpose.OBSERVE` and
# so can never carry an approval, but `purpose` defaults to `REVIEW`, and a repo
# whose CI omits the flag can land an approved or tolerated snapshot on the
# default branch. Counting that as a failure would hold a quarantine open over a
# change somebody already accepted.
_HARD = Q(result__in=(SnapshotResult.CHANGED, SnapshotResult.NEW, SnapshotResult.REMOVED)) & ~Q(
    review_state__in=(ReviewState.APPROVED, ReviewState.TOLERATED)
)
#
# The matched half is restricted to auto-minted rows. A human or agent
# toleration can deliberately accept a diff well over the threshold, and the
# classifier copies that percentage onto every later match, so counting those
# would drive `headroom` to zero and label a snapshot somebody already signed
# off on as `at_risk`. `BELOW_THRESHOLD` needs no such filter: only the
# threshold path writes it.
_SOFT = Q(result=SnapshotResult.UNCHANGED) & (
    Q(classification_reason=ClassificationReason.BELOW_THRESHOLD)
    | Q(
        classification_reason=ClassificationReason.TOLERATED_HASH,
        tolerated_hash_match__reason=ToleratedReason.AUTO_THRESHOLD,
    )
)


@frozen
class _SnapshotKey:
    """One snapshot identity. The same identifier under two run types is two."""

    run_type: str
    identifier: str


@frozen
class _VariantKey:
    """One snapshot's variants, scoped to the baseline they were recorded against.

    No run type: `ToleratedHash` does not carry one, and the classifier looks
    rows up by identifier and baseline hash alone.
    """

    identifier: str
    baseline_hash: str


def get_flakiness_overview(repo_id: UUID) -> _FlakinessRaw:
    """Snapshot identities that render unreliably, or carry a quarantine.

    Scoring, and why it is a rate:
      A count cannot separate one bad afternoon from a chronic flake, and a
      "did anything happen recently" flag scores one failure in a week the same
      as five hundred. So each identity is scored on the share of runs that
      rendered it differently from its baseline, split into the runs that
      failed the gate and the runs a toleration absorbed.

      Rates cover `FLAKINESS_RATE_DAYS`, which is shorter than the window the
      rows are read over. They answer whether a snapshot is failing now, and a
      quarantine over one that stopped failing weeks ago has to become liftable
      rather than keep scoring on failures it no longer produces. The daily
      series still spans the whole window, so a run of failures that predates
      the rate span is visible in the strip.

      The denominator is every completed default-branch run of that run type in
      the rate span, not the runs that rendered this identity. Counting the
      latter needs a scan of every snapshot row in the window, which is the
      shape `baseline_overview` records as too slow to serve per request. The
      approximation only understates, and only for an identity that appeared
      partway through the span.

      Rates ignore which baseline a run compared against. On the default branch
      a legitimate change does not produce a `CHANGED` row at all: the code and
      its baseline land in the same merge, so the next run already compares
      against the new hash. A `CHANGED` row there means the two fell out of
      sync or the render is not deterministic, and both count.

      `variant_count` stays baseline-scoped, because a `ToleratedHash` row is
      stored against a `baseline_hash` and the classifier only matches a row
      whose hash is still the baseline (see `classify_remaining`). Variants
      recorded against a superseded baseline can never match again, so counting
      them would report churn from a snapshot that no longer exists.

    Headroom, and why a soft rate is not enough:
      A snapshot is absorbed only while it stays under both diff thresholds. A
      snapshot always absorbed at 0.01% will not cross; one always absorbed
      just under the line crosses the next time anything nearby is restyled,
      and is a hard failure waiting to happen rather than a stable snapshot.
      `headroom` is what the worst absorbed run in the window leaves free.

      Measured against the pixel threshold only. A `tolerated_hash` row copies
      the diff recorded when the variant was minted, and the image is
      byte-identical to that mint, so the number is exact rather than a
      re-measurement. `ssim_score` is not carried onto matched rows, so the
      structural tier has no equivalent per-run history to read.

    Population:
      Identifiers with a live variant against their current baseline, a hard
      failure in the window, or an active quarantine. Everything else has
      nothing to show, which keeps this an order of magnitude smaller than the
      baselines universe and removes any need to paginate.

    Query shape:
      - 1 query for active quarantines
      - 1 query for the universe runs (one row per run_type, indexed)
      - 1 values-only query for the current baseline hash per identifier
      - 1 grouped query for the rate span's run count per run type
      - 1 grouped query for hard activity per identity and day, which the
        `snapshot_run_result` index serves because non-unchanged rows are rare
      - 1 grouped query for variant count and mean diff
      - 1 grouped query for soft activity per identity and day, bounded to the
        identifiers that can produce a row
      - 1 grouped query for when each baseline last moved, same bound
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
            strip_days=FLAKINESS_WINDOW_DAYS,
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

    # The window every rate, timestamp and strip tick is measured over. Joined
    # on the run rather than passed as a list of run ids: an active repo lands
    # hundreds of default-branch runs in a month, and the same predicate
    # already serves the neighbouring queries here.
    strip_start = today - timedelta(days=FLAKINESS_WINDOW_DAYS - 1)
    rate_start = today - timedelta(days=FLAKINESS_RATE_DAYS - 1)
    in_window = Q(
        run__repo_id=repo_id,
        run__branch__in=run_queries._DEFAULT_BRANCHES,
        run__status=RunStatus.COMPLETED,
        # Calendar days, matching the strip. A timestamp cutoff would reach into
        # the day before the first tick, so `last_flaked_at` could name a day the
        # strip does not draw.
        run__created_at__date__gte=strip_start,
    )

    # The rate denominator, per run type, over the same calendar days the
    # numerators are summed over. A timestamp cutoff here instead would cover
    # part of one more day than `_count_since` reads, so the oldest partial
    # day's runs would sit in the denominator while their failures did not
    # reach the numerator. That deflates every rate, and late in the day it can
    # drop a snapshot failing every run below the `broken` band and mark a
    # quarantine decision-ready while its last failure is still inside the span.
    rate_runs_by_type: dict[str, int] = dict(
        Run.objects.filter(
            repo_id=repo_id,
            branch__in=run_queries._DEFAULT_BRANCHES,
            status=RunStatus.COMPLETED,
            created_at__date__gte=rate_start,
        )
        .values("run_type")
        .annotate(run_count=Count("id"))
        .values_list("run_type", "run_count")
    )

    # Unbounded by identifier on purpose: a snapshot can fail every run without
    # ever recording a variant, and that snapshot is the reason this page
    # exists. It is also the case a quarantine is opened for, so leaving it out
    # would hide every quarantine that is still doing its job.
    hard_activity = _read_activity(in_window=in_window, match=_HARD)

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

    # Only identifiers that can produce a row. Everything else is dropped by the
    # assembly loop below, so scanning it buys nothing.
    reportable_identifiers = list(
        {key.identifier for key in variants_by_pair}
        | {key.identifier for key in hard_activity}
        | {key.identifier for key in active_quarantines_by_key}
    )
    if not reportable_identifiers:
        return _FlakinessRaw.empty(generated_at=now, tracked_total=tracked_total)

    # Bounded by identifier, unlike the hard read above. Absorbed rows are the
    # common case rather than the rare one, so this would otherwise scan most
    # of the window. Nothing is lost: an absorbed row means the classifier
    # matched a live variant or minted one, and either way the identifier is
    # already in the list.
    soft_activity = _read_activity(in_window=in_window, match=_SOFT, identifiers=reportable_identifiers)

    # When each baseline last moved. A real flip on the default branch leaves a
    # CHANGED or REMOVED row in the run that introduced it, because later runs
    # compare against the new committed baseline and see UNCHANGED. That makes
    # `Max` the most recent flip, which stays right when a baseline is reverted
    # to a hash it held before.
    #
    # CHANGED is not only a flip. A snapshot that keeps rendering differently
    # from an unchanged baseline, with no toleration to match it, records
    # CHANGED on every run. `Max` then reports the latest failure instead of the
    # last real move, so the age reads too new for that snapshot. `hard_rate`
    # now names that case directly, so a reader can tell the two apart.
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

    expiry_soon_cutoff = now + timedelta(days=FLAKINESS_EXPIRY_SOON_DAYS)

    # An identity can carry something to report and still have no current
    # baseline: a quarantine opened before the first run, or a snapshot that
    # failed inside the window and then dropped out of the latest
    # default-branch run. Those keys are absent from `baseline_hash_by_key`, so
    # walk them too rather than silently drop what they recorded.
    baseline_less_keys = (active_quarantines_by_key.keys() | hard_activity.keys()) - baseline_hash_by_key.keys()
    scored_keys: list[tuple[_SnapshotKey, str]] = [
        *baseline_hash_by_key.items(),
        *((key, "") for key in baseline_less_keys),
    ]

    rows: list[_FlakinessRow] = []
    for key, baseline_hash in scored_keys:
        variant_key = _VariantKey(identifier=key.identifier, baseline_hash=baseline_hash)
        stats = variants_by_pair.get(variant_key) if baseline_hash else None
        quarantine = active_quarantines_by_key.get(key)
        hard = hard_activity.get(key)
        soft = soft_activity.get(key)
        if stats is None and quarantine is None and hard is None:
            continue

        # Counts and rates describe the rate window; the daily series below
        # covers the whole read window, so the strip can show a run of failures
        # that started before the rates would notice it.
        hard_count = _count_since(hard, rate_start)
        soft_count = _count_since(soft, rate_start)
        # Never below what was actually observed, so a rate cannot exceed 1.0
        # when an identity outlived its run type's run count.
        window_runs = max(rate_runs_by_type.get(key.run_type, 0), hard_count + soft_count)
        # Headroom reads the whole window rather than the rate span: it asks
        # for the worst case a snapshot can produce, and more days are better
        # evidence of that.
        worst_soft_diff = soft.worst_diff_percentage if soft is not None else None
        hard_rate = _rate(hard_count, window_runs)
        headroom = _headroom(worst_soft_diff)
        rows.append(
            _FlakinessRow(
                run_type=key.run_type,
                identifier=key.identifier,
                variant_count=stats.count if stats is not None else 0,
                hard_count=hard_count,
                soft_count=soft_count,
                window_runs=window_runs,
                hard_rate=hard_rate,
                soft_rate=_rate(soft_count, window_runs),
                last_flaked_at=_latest(
                    hard.last_at if hard is not None else None,
                    soft.last_at if soft is not None else None,
                ),
                avg_diff_percentage=stats.avg_diff_percentage if stats is not None else None,
                worst_soft_diff_percentage=worst_soft_diff,
                headroom=headroom,
                daily_hard_counts=_daily_series(
                    hard.daily if hard is not None else {},
                    strip_start=strip_start,
                    length=FLAKINESS_WINDOW_DAYS,
                ),
                daily_soft_counts=_daily_series(
                    soft.daily if soft is not None else {},
                    strip_start=strip_start,
                    length=FLAKINESS_WINDOW_DAYS,
                ),
                baseline_moved_at=baseline_moved_at_by_key.get(key),
                state=_state(
                    hard_rate=hard_rate,
                    soft_count=soft_count,
                    headroom=headroom,
                    window_runs=window_runs,
                ),
                quarantine=quarantine,
                needs_decision=_needs_decision(
                    quarantine=quarantine,
                    hard_count=hard_count,
                    expiry_soon_cutoff=expiry_soon_cutoff,
                ),
            )
        )

    # Ordering decides what survives the cap, so the rows somebody has to act on
    # come first: a decision waiting on a human, then the state ladder, then a
    # quarantine, so that among equally urgent rows the ones somebody is
    # already relying on are the last to be cut.
    #
    # Rows that never flaked sort last within their group against an aware
    # epoch, because `last_flaked_at` is aware and mixing it with a naive
    # datetime raises.
    never = datetime.min.replace(tzinfo=UTC)
    rows.sort(
        key=lambda row: (
            row.needs_decision,
            _STATE_URGENCY[row.state],
            row.quarantine is not None,
            row.hard_rate,
            row.soft_rate,
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
        totals_broken=sum(1 for row in rows if row.state == FlakinessState.BROKEN),
        totals_unstable=sum(1 for row in rows if row.state == FlakinessState.UNSTABLE),
        totals_at_risk=sum(1 for row in rows if row.state == FlakinessState.AT_RISK),
        totals_noisy=sum(1 for row in rows if row.state == FlakinessState.NOISY),
        totals_clean=sum(1 for row in rows if row.state == FlakinessState.CLEAN),
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
            hard_count=0,
            soft_count=0,
            window_runs=0,
            hard_rate=0.0,
            soft_rate=0.0,
            last_flaked_at=None,
            avg_diff_percentage=None,
            worst_soft_diff_percentage=None,
            headroom=None,
            daily_hard_counts=[0] * strip_days,
            daily_soft_counts=[0] * strip_days,
            baseline_moved_at=None,
            state=FlakinessState.CLEAN,
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
        totals_broken=0,
        totals_unstable=0,
        totals_at_risk=0,
        totals_noisy=0,
        totals_clean=len(rows),
        # Totals count the whole population, as they do on the normal path, so
        # the tiles stay right when the list is capped.
        totals_quarantined=len(rows),
        totals_needs_decision=len(rows),
        by_run_type=dict(Counter(row.run_type for row in rows)),
        truncated=len(listed) < len(rows),
        generated_at=generated_at,
    )


def _read_activity(
    *,
    in_window: Q,
    match: Q,
    identifiers: list[str] | None = None,
) -> dict[_SnapshotKey, _Activity]:
    """Window activity per snapshot identity, for the rows `match` selects.

    Grouped by day so one query serves both the rate and the activity strip:
    the total is summed from the days rather than asked for separately.
    """
    queryset = RunSnapshot.objects.filter(in_window).filter(match)
    if identifiers is not None:
        queryset = queryset.filter(identifier__in=identifiers)

    daily: dict[_SnapshotKey, dict[date, int]] = defaultdict(dict)
    totals: Counter[_SnapshotKey] = Counter()
    last_at: dict[_SnapshotKey, datetime] = {}
    worst: dict[_SnapshotKey, float] = {}
    for run_type, identifier, day, day_count, latest, worst_diff in (
        queryset.annotate(day=TruncDate("run__created_at"))
        .values("run__run_type", "identifier", "day")
        .annotate(
            day_count=Count("id"),
            latest=Max("run__created_at"),
            worst_diff=Max("diff_percentage"),
        )
        .values_list("run__run_type", "identifier", "day", "day_count", "latest", "worst_diff")
    ):
        key = _SnapshotKey(run_type=run_type, identifier=identifier)
        daily[key][day] = day_count
        totals[key] += day_count
        seen_last = last_at.get(key)
        if latest is not None and (seen_last is None or latest > seen_last):
            last_at[key] = latest
        seen_worst = worst.get(key)
        if worst_diff is not None and (seen_worst is None or worst_diff > seen_worst):
            worst[key] = worst_diff

    return {
        key: _Activity(
            total=total,
            last_at=last_at.get(key),
            daily=daily[key],
            worst_diff_percentage=worst.get(key),
        )
        for key, total in totals.items()
    }


def _count_since(activity: _Activity | None, start: date) -> int:
    """Runs on or after `start`, summed from the per-day buckets already read.

    The daily grouping means the rate span costs no extra query: it is a slice
    of the series the strip renders.
    """
    if activity is None:
        return 0
    return sum(count for day, count in activity.daily.items() if day >= start)


def _rate(count: int, window_runs: int) -> float:
    """Share of the window's runs, or 0.0 when the window holds no runs."""
    return count / window_runs if window_runs else 0.0


def _headroom(worst_soft_diff_percentage: float | None) -> float | None:
    """Fraction of the pixel threshold the worst absorbed run leaves free.

    1.0 means the snapshot rendered identically to its baseline every time it
    was absorbed; 0.0 means it reached the threshold and only luck kept it on
    the passing side. None when nothing was absorbed, which is not the same as
    full headroom and must not read as a safe row.
    """
    if worst_soft_diff_percentage is None:
        return None
    return max(0.0, (PIXEL_DIFF_THRESHOLD_PERCENT - worst_soft_diff_percentage) / PIXEL_DIFF_THRESHOLD_PERCENT)


def _state(*, hard_rate: float, soft_count: int, headroom: float | None, window_runs: int) -> str:
    """Where a snapshot sits on the urgency ladder, and so what it is asking for.

    Ordered by hard failures first, because those are the ones that stopped
    somebody merging. `broken` needs a run count behind it: one failure out of
    two runs is a 50% rate that means nothing, and calling it broken would send
    a reader to fix a baseline on the strength of a single bad render.
    """
    if hard_rate >= FLAKINESS_BROKEN_RATE and window_runs >= FLAKINESS_MIN_WINDOW_RUNS:
        return FlakinessState.BROKEN
    if hard_rate > 0:
        return FlakinessState.UNSTABLE
    if soft_count == 0:
        return FlakinessState.CLEAN
    if headroom is not None and headroom < FLAKINESS_MIN_HEADROOM:
        return FlakinessState.AT_RISK
    return FlakinessState.NOISY


# How far up the ladder each state sits, for ordering against the entry cap.
# Keyed by `str` because `_state` returns one: `FlakinessState` is a `StrEnum`,
# so the members are the keys either way.
_STATE_URGENCY: dict[str, int] = {
    FlakinessState.BROKEN: 4,
    FlakinessState.UNSTABLE: 3,
    FlakinessState.AT_RISK: 2,
    FlakinessState.NOISY: 1,
    FlakinessState.CLEAN: 0,
}


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
    hard_count: int,
    expiry_soon_cutoff: datetime,
) -> bool:
    """Whether an active quarantine has stopped matching what it was opened for.

    Three ways that happens: it already ran out, it is about to, or the
    snapshot it covers has stopped failing the gate. An expired entry is not in
    `quarantine` to begin with, because the caller filters on `expires_at`, so
    only the last two are testable here.

    Turns on hard failures rather than on variants. A quarantine is opened for
    a snapshot that fails the gate, and the ways a snapshot fails the gate -
    a diff over a threshold, a missing baseline, a missing render - are exactly
    the ways that record no variant at all. Reading variants therefore said
    "gone clean, lift it" about every snapshot still failing every run, and
    lifting it turned the gate red again.

    A rate span holding few runs, or none, also returns True, and that is
    deliberate rather than an unguarded edge. "It stopped failing" and "this
    run type has not run for a week" both leave a human to decide what the
    quarantine is still for. The row reports `window_runs` beside the rate, so
    a reader can tell the two apart.
    """
    if quarantine is None:
        return False
    if hard_count == 0:
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
class _Activity:
    """What one snapshot identity did in the window, for one kind of difference.

    `worst_diff_percentage` is None when the rows carry no pixel diff, which is
    every hard row classified by the structural tier.
    """

    total: int
    last_at: datetime | None
    daily: dict[date, int]
    worst_diff_percentage: float | None


@frozen
class _FlakinessRow:
    """One scored snapshot identity, before thumbnails and users are attached."""

    run_type: str
    identifier: str
    variant_count: int
    hard_count: int
    soft_count: int
    window_runs: int
    hard_rate: float
    soft_rate: float
    last_flaked_at: datetime | None
    avg_diff_percentage: float | None
    worst_soft_diff_percentage: float | None
    headroom: float | None
    daily_hard_counts: list[int]
    daily_soft_counts: list[int]
    baseline_moved_at: datetime | None
    state: str
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
    totals_broken: int
    totals_unstable: int
    totals_at_risk: int
    totals_noisy: int
    totals_clean: int
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
            totals_broken=0,
            totals_unstable=0,
            totals_at_risk=0,
            totals_noisy=0,
            totals_clean=0,
            totals_quarantined=0,
            totals_needs_decision=0,
            by_run_type={},
            truncated=False,
            generated_at=generated_at,
        )
