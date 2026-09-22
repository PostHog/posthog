"""The baselines overview aggregate that backs the snapshot overview scene."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from uuid import UUID

from django.db.models import Avg, Count, Q, QuerySet
from django.utils import timezone

from posthog.dataclasses import frozen

from ..facade.enums import INTENTIONAL_TOLERATE_REASONS, RunStatus, SnapshotResult
from ..models import QuarantinedIdentifier, Run, RunSnapshot, ToleratedHash
from . import run_queries, toleration
from .run_queries import SnapshotKey

# A baseline counts as frequently tolerated at this many intentional tolerations in the window.
_FREQUENT_TOLERATE_MIN = 3


def get_baselines_overview(repo_id: UUID) -> _BaselineOverviewRaw:
    """Universe of identifiers with a current baseline, plus aggregates.

    The "current baseline" universe is anchored on the latest non-superseded run
    on the default branch (master/main) for each `run_type`. One row per
    `(run_type, identifier)` — the closest thing to "what we'd compare a new
    capture against right now".

    Performance shape:
      - 1 query for the universe runs (one row per run_type, indexed)
      - 1 query for the universe rows (with thumbnail + artifact prefetch)
      - 2 grouped queries for tolerate counts (30d + 90d)
      - 2 queries for the accepted variants standing against the current baseline
      - 1 grouped query for active quarantines
      - 1 grouped query for lifetime baseline-flip count
      - 2 queries for the recent-drift average (resolve last-N runs, aggregate)
      - 3 cheap aggregate queries for totals
    """
    from ..facade.contracts import BASELINE_DRIFT_RECENT_RUN_COUNT, BASELINE_OVERVIEW_MAX_ENTRIES, VARIANT_PILEUP_MIN

    now = timezone.now()

    # Find the latest *completed* run on the default branch per (repo, branch, run_type).
    universe_runs = run_queries.latest_default_branch_runs(repo_id)
    universe_run_ids = [r.id for r in universe_runs]
    if not universe_run_ids:
        return _empty_overview(now)

    universe_qs = _universe_queryset(universe_run_ids)
    total_universe = universe_qs.count()
    truncated = total_universe > BASELINE_OVERVIEW_MAX_ENTRIES
    universe = list(universe_qs[:BASELINE_OVERVIEW_MAX_ENTRIES]) if truncated else list(universe_qs)
    # Per-entry aggregates (tolerate counts, sparklines) only need to cover the
    # entries we'll return. Totals must scope across the *full* universe,
    # otherwise truncation makes them undercount in misleading ways (a 6000-id
    # repo would show 0 frequently-tolerated if all of them sat past the slice).
    universe_identifiers = list({s.identifier for s in universe})
    # `.order_by()` clears the ordering before DISTINCT. Django appends an ORDER BY column to
    # the select list of a DISTINCT query, so the `-run__completed_at` ordering above would join
    # the DISTINCT key and yield one row per (identifier, run) rather than one per identifier.
    # The list feeds `identifier__in` filters, so that pushes the parameter count toward the
    # Postgres bind-parameter limit and adds a join and a sort that the caller has no use for.
    full_universe_identifiers = (
        list(universe_qs.order_by().values_list("identifier", flat=True).distinct())
        if truncated
        else universe_identifiers
    )

    # Accepted variants still standing against each baseline's current hash. Scoped to the
    # whole universe rather than the truncated slice, because the totals below read it too.
    active_variants_by_key = toleration.count_active_variants_against_current_baseline(
        repo_id, now=now, newest_run_by_type=run_queries.newest_run_by_run_type(universe_runs)
    )
    active_quarantines_by_key = _active_quarantines_by_key(repo_id, universe_identifiers, now=now)

    # Per-baseline stability signals: a lifetime baseline-flip count and a smoothed
    # recent-drift average. Both cover the whole repo history rather than a set of
    # identifiers, so an empty universe is the only thing that can skip them. They
    # replace a daily-bucket sparkline that had to scan millions of RunSnapshot rows
    # on every request (~7s, OOMed on the web pod for repos with thousands of
    # identifiers — see git history). Both are scoped tightly enough to finish in
    # tens of ms.
    if universe_identifiers:
        change_count_by_key = _baseline_change_counts_by_key(repo_id)
        recent_drift_by_key = _recent_drift_by_key(repo_id, recent_run_count=BASELINE_DRIFT_RECENT_RUN_COUNT)
    else:
        change_count_by_key = {}
        recent_drift_by_key = {}

    # `active_quarantines_by_key` was built from the truncated set above (per-entry
    # attached). Re-query for the totals so they cover the full universe.
    if truncated and full_universe_identifiers:
        quarantined_id_count = _quarantined_identifier_count(repo_id, full_universe_identifiers, now=now)
    else:
        quarantined_id_count = len({key.identifier for key in active_quarantines_by_key})

    return _BaselineOverviewRaw(
        entries=universe,
        tolerate_30d_by_id=_tolerate_counts_by_identifier(
            repo_id, universe_identifiers, since=now - timedelta(days=30)
        ),
        tolerate_90d_by_id=_tolerate_counts_by_identifier(
            repo_id, universe_identifiers, since=now - timedelta(days=90)
        ),
        active_variants_by_key=active_variants_by_key,
        active_quarantines_by_key=active_quarantines_by_key,
        change_count_by_key=change_count_by_key,
        recent_drift_by_key=recent_drift_by_key,
        totals_all=total_universe,
        totals_recent=_recently_tolerated_count(repo_id, full_universe_identifiers, since=now - timedelta(days=30)),
        totals_frequent=_frequently_tolerated_count(repo_id, full_universe_identifiers, since=now - timedelta(days=90)),
        totals_quarantined=quarantined_id_count,
        totals_variant_pileups=sum(1 for count in active_variants_by_key.values() if count >= VARIANT_PILEUP_MIN),
        by_run_type=_counts_by_run_type(universe_qs, universe, truncated=truncated),
        truncated=truncated,
        generated_at=now,
    )


def _empty_overview(now: datetime) -> _BaselineOverviewRaw:
    return _BaselineOverviewRaw(
        entries=[],
        tolerate_30d_by_id={},
        tolerate_90d_by_id={},
        active_variants_by_key={},
        active_quarantines_by_key={},
        change_count_by_key={},
        recent_drift_by_key={},
        totals_all=0,
        totals_recent=0,
        totals_frequent=0,
        totals_quarantined=0,
        totals_variant_pileups=0,
        by_run_type={},
        truncated=False,
        generated_at=now,
    )


def _universe_queryset(universe_run_ids: list[UUID]) -> QuerySet[RunSnapshot]:
    """The universe rows. select_related the chain we need for thumbnails."""
    return (
        RunSnapshot.objects.filter(run_id__in=universe_run_ids)
        .select_related("run", "current_artifact__thumbnail")
        .only(
            "identifier",
            "metadata",
            "run__id",
            "run__run_type",
            "run__completed_at",
            "run__created_at",
            "current_artifact__width",
            "current_artifact__height",
            "current_artifact__thumbnail__content_hash",
        )
        # Stable ordering so truncation is deterministic; newest baselines first.
        .order_by("-run__completed_at", "identifier")
    )


def _intentional_tolerations(repo_id: UUID, identifiers: list[str], since: datetime) -> QuerySet[ToleratedHash]:
    """Tolerations a person chose, in a rolling window. Excludes AUTO_THRESHOLD."""
    return ToleratedHash.objects.filter(
        repo_id=repo_id,
        identifier__in=identifiers,
        reason__in=INTENTIONAL_TOLERATE_REASONS,
        created_at__gte=since,
    )


def _tolerate_counts_by_identifier(repo_id: UUID, identifiers: list[str], since: datetime) -> dict[str, int]:
    """Per-identifier tolerate count in the window. Single grouped query."""
    if not identifiers:
        return {}
    return dict(
        _intentional_tolerations(repo_id, identifiers, since)
        .values_list("identifier")
        .annotate(c=Count("id"))
        .values_list("identifier", "c")
    )


def _recently_tolerated_count(repo_id: UUID, identifiers: list[str], since: datetime) -> int:
    """Distinct identifiers with at least one intentional toleration in the window."""
    if not identifiers:
        return 0
    return _intentional_tolerations(repo_id, identifiers, since).values("identifier").distinct().count()


def _frequently_tolerated_count(repo_id: UUID, identifiers: list[str], since: datetime) -> int:
    """Distinct identifiers tolerated repeatedly in the window."""
    if not identifiers:
        return 0
    return (
        _intentional_tolerations(repo_id, identifiers, since)
        .values("identifier")
        .annotate(c=Count("id"))
        .filter(c__gte=_FREQUENT_TOLERATE_MIN)
        .count()
    )


def _active_quarantines_qs(repo_id: UUID, identifiers: list[str], now: datetime) -> QuerySet[QuarantinedIdentifier]:
    return QuarantinedIdentifier.objects.filter(
        repo_id=repo_id,
        identifier__in=identifiers,
    ).filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))


def _active_quarantines_by_key(
    repo_id: UUID, identifiers: list[str], now: datetime
) -> dict[SnapshotKey, QuarantinedIdentifier]:
    """Active quarantines, scoped to the universe identifiers.

    Quarantine is per `(repo, run_type, identifier)`. We hydrate the full row (not
    just identity) so the overview can render reason / expiry / who / source-run
    inline without a per-card fetch. `select_related("source_run")` is a single
    JOIN, capped by `BASELINE_OVERVIEW_MAX_ENTRIES`. `Run.metadata` (JSONField)
    and `Run.error_message` (TextField) can be large and aren't needed by the
    summary — defer them to keep the response light.
    """
    if not identifiers:
        return {}
    by_key: dict[SnapshotKey, QuarantinedIdentifier] = {}
    for q in (
        _active_quarantines_qs(repo_id, identifiers, now)
        .select_related("source_run")
        .defer("source_run__metadata", "source_run__error_message")
        .order_by("-created_at")
    ):
        key = SnapshotKey(run_type=q.run_type, identifier=q.identifier)
        # Multiple active rows for the same key shouldn't happen — create
        # auto-supersedes prior — but if it does, keep the latest (sorted
        # above) and ignore the rest.
        if key not in by_key:
            by_key[key] = q
    return by_key


def _quarantined_identifier_count(repo_id: UUID, identifiers: list[str], now: datetime) -> int:
    return _active_quarantines_qs(repo_id, identifiers, now).values("identifier").distinct().count()


def _baseline_change_counts_by_key(repo_id: UUID) -> dict[SnapshotKey, int]:
    """Lifetime baseline-flip count per baseline.

    COUNT(*) WHERE result IN ('changed','removed') across all completed
    master/main runs ever. Real baseline flips on master leave a CHANGED/REMOVED
    row in the run that introduced them (subsequent runs see UNCHANGED against
    the new YAML baseline), so this count IS the number of times the YAML moved.
    "Ever" reaches back as far as retention keeps default-branch runs, which is
    `retention.DEFAULT_BRANCH_RUN_RETENTION_DAYS`. Postgres uses the
    `snapshot_run_result` index on (run_id, result) to bitmap-scan straight to
    the rare event rows (~1k of millions). No window function, no per-row LAG
    comparison.
    """
    return {
        SnapshotKey(run_type=run_type, identifier=identifier): c
        for identifier, run_type, c in RunSnapshot.objects.filter(
            run__repo_id=repo_id,
            run__branch__in=run_queries._DEFAULT_BRANCHES,
            run__status=RunStatus.COMPLETED,
            result__in=(SnapshotResult.CHANGED, SnapshotResult.REMOVED),
        )
        .values("identifier", "run__run_type")
        .annotate(c=Count("id"))
        .values_list("identifier", "run__run_type", "c")
    }


def _recent_run_ids_by_run_type(repo_id: UUID, recent_run_count: int) -> list[UUID]:
    """The last N completed default-branch runs per run type.

    Top-N per run_type via window function. There's no pure-ORM equivalent:
    Postgres doesn't allow filtering on a window result, and a per-run_type loop
    balloons to thousands of queries on repos where each Storybook story
    registers as its own run_type (benchmarked: 4ms raw vs 5.6s loop on a 30k-run
    repo with 2154 run_types). The query is parameterized — every dynamic value
    passes through %s binding, no string concatenation, table name comes from the
    model. nosemgrep is required because the rule blanket-flags any .raw() use.
    """
    recent_run_sql = f"""
        SELECT id, run_type FROM (
            SELECT id, run_type,
                   ROW_NUMBER() OVER (PARTITION BY run_type ORDER BY created_at DESC) AS rn
            FROM {Run._meta.db_table}
            WHERE repo_id = %s AND branch = ANY(%s) AND status = %s
        ) ranked WHERE rn <= %s
    """  # nosemgrep: python.django.security.audit.raw-query.avoid-raw-sql
    return [
        r.id
        for r in Run.objects.raw(  # nosemgrep: python.django.security.audit.raw-query.avoid-raw-sql
            recent_run_sql,
            [
                str(repo_id),
                list(run_queries._DEFAULT_BRANCHES),
                RunStatus.COMPLETED,
                recent_run_count,
            ],
        )
    ]


def _recent_drift_by_key(repo_id: UUID, recent_run_count: int) -> dict[SnapshotKey, float]:
    """Smoothed recent-drift average per baseline.

    AVG(diff_percentage) over the last N master/main completed runs per
    `run_type`. Bounded by run count, not by time window — caps the scanned set
    regardless of CI cadence. We resolve the run IDs first (sub-ms) and aggregate
    via PK-indexed run_id__in, otherwise the planner inlines a CTE that produces
    a ROW_NUMBER plan over the full RunSnapshot table.
    """
    recent_run_ids = _recent_run_ids_by_run_type(repo_id, recent_run_count)
    if not recent_run_ids:
        return {}
    return {
        SnapshotKey(run_type=run_type, identifier=identifier): drift_avg
        for identifier, run_type, drift_avg in RunSnapshot.objects.filter(run_id__in=recent_run_ids)
        .values("identifier", "run__run_type")
        .annotate(drift_avg=Avg("diff_percentage", filter=Q(diff_percentage__gt=0)))
        .values_list("identifier", "run__run_type", "drift_avg")
        if drift_avg is not None
    }


def _counts_by_run_type(
    universe_qs: QuerySet[RunSnapshot], entries: list[RunSnapshot], *, truncated: bool
) -> dict[str, int]:
    """Every entry in the universe, per run type.

    Aggregate query under truncation so it doesn't undercount; in-memory Counter
    when not truncated (we already paid for the row hydration).
    """
    if truncated:
        return dict(
            universe_qs.values_list("run__run_type")
            .order_by()
            .annotate(c=Count("id"))
            .values_list("run__run_type", "c")
        )
    return dict(Counter(s.run.run_type for s in entries))


@frozen
class _BaselineOverviewRaw:
    """Internal raw shape — the facade layer reshapes this into the public DTOs.

    Kept private to this package so that contract changes don't ripple through here.
    """

    entries: list[RunSnapshot]
    tolerate_30d_by_id: dict[str, int]
    tolerate_90d_by_id: dict[str, int]
    # Accepted variants standing against each baseline's current hash. Only non-zero counts
    # are present.
    active_variants_by_key: dict[SnapshotKey, int]
    # Latest active QuarantinedIdentifier (with `source_run` preloaded) for each
    # `(run_type, identifier)` in the universe — lets the facade build the rich
    # quarantine summary embedded on each BaselineEntry. Membership doubles as
    # the "is_quarantined" signal — no separate set needed.
    active_quarantines_by_key: dict[SnapshotKey, QuarantinedIdentifier]
    # Stability signals keyed per identity because the same identifier in
    # different run types is a different baseline; merging would bleed storybook
    # stability into playwright stability.
    change_count_by_key: dict[SnapshotKey, int]
    recent_drift_by_key: dict[SnapshotKey, float]
    totals_all: int
    totals_recent: int
    totals_frequent: int
    totals_quarantined: int
    totals_variant_pileups: int
    by_run_type: dict[str, int]
    truncated: bool
    generated_at: datetime
