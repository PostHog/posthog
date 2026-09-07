"""The baselines overview aggregate that backs the snapshot overview scene."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from uuid import UUID

from django.db.models import Avg, Count, Q
from django.utils import timezone

from posthog.dataclasses import frozen

from ..facade.enums import INTENTIONAL_TOLERATE_REASONS, RunStatus, SnapshotResult
from ..models import QuarantinedIdentifier, Run, RunSnapshot, ToleratedHash
from . import run_queries


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
      - 1 grouped query for active quarantines
      - 1 grouped query for lifetime baseline-flip count
      - 2 queries for the recent-drift average (resolve last-N runs, aggregate)
      - 3 cheap aggregate queries for totals
    """
    from datetime import timedelta

    from ..facade.contracts import BASELINE_DRIFT_RECENT_RUN_COUNT, BASELINE_OVERVIEW_MAX_ENTRIES

    now = timezone.now()

    # 1. Find the latest *completed* run on the default branch per (repo,
    # branch, run_type). Filtering on `superseded_by IS NULL` looks tempting
    # but is wrong here: a freshly started PENDING/PROCESSING master run is
    # un-superseded yet has zero (or sparse) RunSnapshots ingested, and would
    # collapse the universe to whatever it has loaded so far. `status=completed`
    # makes the universe fall through to the most recent fully-ingested run.
    universe_runs = list(
        Run.objects.filter(
            repo_id=repo_id,
            branch__in=run_queries._DEFAULT_BRANCHES,
            status=RunStatus.COMPLETED,
        )
        .order_by("repo_id", "branch", "run_type", "-created_at")
        .distinct("repo_id", "branch", "run_type")
        .only("id", "run_type", "completed_at", "created_at")
    )
    universe_run_ids = [r.id for r in universe_runs]
    if not universe_run_ids:
        return _BaselineOverviewRaw(
            entries=[],
            tolerate_30d_by_id={},
            tolerate_90d_by_id={},
            active_quarantines_by_key={},
            change_count_by_key={},
            recent_drift_by_key={},
            totals_all=0,
            totals_recent=0,
            totals_frequent=0,
            totals_quarantined=0,
            by_run_type={},
            truncated=False,
            generated_at=now,
        )

    # 2. Pull the universe rows. select_related the chain we need for thumbnails.
    universe_qs = (
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
    total_universe = universe_qs.count()
    truncated = total_universe > BASELINE_OVERVIEW_MAX_ENTRIES
    universe = list(universe_qs[:BASELINE_OVERVIEW_MAX_ENTRIES]) if truncated else list(universe_qs)
    # Per-entry aggregates (tolerate counts, sparklines) only need to cover the
    # entries we'll return. Totals must scope across the *full* universe,
    # otherwise truncation makes them undercount in misleading ways (a 6000-id
    # repo would show 0 frequently-tolerated if all of them sat past the slice).
    universe_identifiers = list({s.identifier for s in universe})
    if truncated:
        full_universe_identifiers = list(universe_qs.values_list("identifier", flat=True).distinct())
    else:
        full_universe_identifiers = universe_identifiers

    # 3a. Tolerate counts in 30d / 90d windows. Single grouped query each.
    tolerate_30d_by_id: dict[str, int] = {}
    tolerate_90d_by_id: dict[str, int] = {}
    if universe_identifiers:
        tol_30d_cutoff = now - timedelta(days=30)
        tol_90d_cutoff = now - timedelta(days=90)
        for identifier, count in (
            ToleratedHash.objects.filter(
                repo_id=repo_id,
                identifier__in=universe_identifiers,
                reason__in=INTENTIONAL_TOLERATE_REASONS,
                created_at__gte=tol_30d_cutoff,
            )
            .values_list("identifier")
            .annotate(c=Count("id"))
            .values_list("identifier", "c")
        ):
            tolerate_30d_by_id[identifier] = count
        for identifier, count in (
            ToleratedHash.objects.filter(
                repo_id=repo_id,
                identifier__in=universe_identifiers,
                reason__in=INTENTIONAL_TOLERATE_REASONS,
                created_at__gte=tol_90d_cutoff,
            )
            .values_list("identifier")
            .annotate(c=Count("id"))
            .values_list("identifier", "c")
        ):
            tolerate_90d_by_id[identifier] = count

    # 3b. Active quarantines for this repo, scoped to the universe identifiers
    # AND the run_types they live on (quarantine is per (repo, run_type, id)).
    # We hydrate the full row (not just identity) so the overview can render
    # reason / expiry / who / source-run inline without a per-card fetch.
    # `select_related("source_run")` is a single JOIN, capped by
    # `BASELINE_OVERVIEW_MAX_ENTRIES`. `Run.metadata` (JSONField) and
    # `Run.error_message` (TextField) can be large and aren't needed by the
    # summary — defer them to keep the response light.
    active_quarantines_by_key: dict[tuple[str, str], QuarantinedIdentifier] = {}
    if universe_identifiers:
        for q in (
            QuarantinedIdentifier.objects.filter(
                repo_id=repo_id,
                identifier__in=universe_identifiers,
            )
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
            .select_related("source_run")
            .defer("source_run__metadata", "source_run__error_message")
            .order_by("-created_at")
        ):
            key = (q.run_type, q.identifier)
            # Multiple active rows for the same key shouldn't happen — create
            # auto-supersedes prior — but if it does, keep the latest (sorted
            # above) and ignore the rest.
            if key not in active_quarantines_by_key:
                active_quarantines_by_key[key] = q

    # 3c. Per-baseline stability signals: a lifetime baseline-flip count and a
    # smoothed recent-drift average. Replaces a daily-bucket sparkline that
    # had to scan millions of RunSnapshot rows on every request (~7s, OOMed on
    # the web pod for repos with thousands of identifiers — see git history).
    # Both queries here are scoped tightly enough to finish in tens of ms:
    #
    #   change_count_by_key: COUNT(*) WHERE result IN ('changed','removed')
    #     across all completed master/main runs ever. Real baseline flips on
    #     master leave a CHANGED/REMOVED row in the run that introduced them
    #     (subsequent runs see UNCHANGED against the new YAML baseline), so
    #     this count IS the number of times the YAML moved. Postgres uses
    #     the `snapshot_run_result` index on (run_id, result) to bitmap-scan
    #     straight to the rare event rows (~1k of millions). No window
    #     function, no per-row LAG comparison.
    #
    #   recent_drift_by_key: AVG(diff_percentage) over the last 10 master/
    #     main completed runs per (run_type). Bounded by run count, not by
    #     time window — caps the scanned set regardless of CI cadence. We
    #     resolve the run IDs first (sub-ms) and aggregate via PK-indexed
    #     run_id__in, otherwise the planner inlines a CTE that produces a
    #     ROW_NUMBER plan over the full RunSnapshot table.
    change_count_by_key: dict[tuple[str, str], int] = {}
    recent_drift_by_key: dict[tuple[str, str], float] = {}
    if universe_identifiers:
        for identifier, run_type, c in (
            RunSnapshot.objects.filter(
                run__repo_id=repo_id,
                run__branch__in=run_queries._DEFAULT_BRANCHES,
                run__status=RunStatus.COMPLETED,
                result__in=(SnapshotResult.CHANGED, SnapshotResult.REMOVED),
            )
            .values("identifier", "run__run_type")
            .annotate(c=Count("id"))
            .values_list("identifier", "run__run_type", "c")
        ):
            change_count_by_key[(run_type, identifier)] = c

        # Top-N per run_type via window function. There's no pure-ORM
        # equivalent: Postgres doesn't allow filtering on a window result,
        # and a per-run_type loop balloons to thousands of queries on repos
        # where each Storybook story registers as its own run_type
        # (benchmarked: 4ms raw vs 5.6s loop on a 30k-run repo with 2154
        # run_types). The query is parameterized — every dynamic value
        # passes through %s binding, no string concatenation, table name
        # comes from the model. nosemgrep is required because the rule
        # blanket-flags any .raw() use.
        recent_run_sql = f"""
            SELECT id, run_type FROM (
                SELECT id, run_type,
                       ROW_NUMBER() OVER (PARTITION BY run_type ORDER BY created_at DESC) AS rn
                FROM {Run._meta.db_table}
                WHERE repo_id = %s AND branch = ANY(%s) AND status = %s
            ) ranked WHERE rn <= %s
        """  # nosemgrep: python.django.security.audit.raw-query.avoid-raw-sql
        recent_run_ids = list(
            Run.objects.raw(  # nosemgrep: python.django.security.audit.raw-query.avoid-raw-sql
                recent_run_sql,
                [
                    str(repo_id),
                    list(run_queries._DEFAULT_BRANCHES),
                    RunStatus.COMPLETED,
                    BASELINE_DRIFT_RECENT_RUN_COUNT,
                ],
            )
        )
        if recent_run_ids:
            for identifier, run_type, drift_avg in (
                RunSnapshot.objects.filter(run_id__in=[r.id for r in recent_run_ids])
                .values("identifier", "run__run_type")
                .annotate(drift_avg=Avg("diff_percentage", filter=Q(diff_percentage__gt=0)))
                .values_list("identifier", "run__run_type", "drift_avg")
            ):
                if drift_avg is not None:
                    recent_drift_by_key[(run_type, identifier)] = drift_avg

    # 4. Totals computed across the *full* universe (not the truncated slice)
    # so the stat row stays correct when the entries are clipped.
    if truncated:
        # Re-issue a small COUNT-only query for accurate totals across the
        # universe; we already have the truncated list in memory.
        totals_all = total_universe
    else:
        totals_all = len(universe)

    # Recently / frequently tolerated — counts of distinct identifiers with
    # ≥1 (or ≥3) intentional tolerations in the rolling window. Scope across
    # the *full* universe so the stat row stays correct under truncation, and
    # match the per-entry counts above by excluding AUTO_THRESHOLD.
    recent_cutoff = now - timedelta(days=30)
    frequent_cutoff = now - timedelta(days=90)
    recent_ids: set[str] = set()
    frequent_ids: set[str] = set()
    if full_universe_identifiers:
        recent_ids = set(
            ToleratedHash.objects.filter(
                repo_id=repo_id,
                identifier__in=full_universe_identifiers,
                reason__in=INTENTIONAL_TOLERATE_REASONS,
                created_at__gte=recent_cutoff,
            )
            .values_list("identifier", flat=True)
            .distinct()
        )
        frequent_grouped = (
            ToleratedHash.objects.filter(
                repo_id=repo_id,
                identifier__in=full_universe_identifiers,
                reason__in=INTENTIONAL_TOLERATE_REASONS,
                created_at__gte=frequent_cutoff,
            )
            .values("identifier")
            .annotate(c=Count("id"))
            .filter(c__gte=3)
            .values_list("identifier", flat=True)
        )
        frequent_ids = set(frequent_grouped)

    # `active_quarantines_by_key` was built from the truncated set above (per-entry
    # attached). Re-query for the totals so they cover the full universe.
    if truncated and full_universe_identifiers:
        quarantined_id_count = (
            QuarantinedIdentifier.objects.filter(
                repo_id=repo_id,
                identifier__in=full_universe_identifiers,
            )
            .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=now))
            .values("identifier")
            .distinct()
            .count()
        )
    else:
        quarantined_id_count = len({identifier for _, identifier in active_quarantines_by_key})

    # by_run_type counts every entry in the universe. Aggregate query under
    # truncation so it doesn't undercount; in-memory Counter when not truncated
    # (we already paid for the row hydration).
    if truncated:
        by_run_type = dict(
            universe_qs.values_list("run__run_type")
            .order_by()
            .annotate(c=Count("id"))
            .values_list("run__run_type", "c")
        )
    else:
        by_run_type = dict(Counter(s.run.run_type for s in universe))

    return _BaselineOverviewRaw(
        entries=universe,
        tolerate_30d_by_id=tolerate_30d_by_id,
        tolerate_90d_by_id=tolerate_90d_by_id,
        active_quarantines_by_key=active_quarantines_by_key,
        change_count_by_key=change_count_by_key,
        recent_drift_by_key=recent_drift_by_key,
        totals_all=totals_all,
        totals_recent=len(recent_ids),
        totals_frequent=len(frequent_ids),
        totals_quarantined=quarantined_id_count,
        by_run_type=by_run_type,
        truncated=truncated,
        generated_at=now,
    )


@frozen
class _BaselineOverviewRaw:
    """Internal raw shape — the facade layer reshapes this into the public DTOs.

    Kept private to this package so that contract changes don't ripple through here.
    """

    entries: list[RunSnapshot]
    tolerate_30d_by_id: dict[str, int]
    tolerate_90d_by_id: dict[str, int]
    # Latest active QuarantinedIdentifier (with `source_run` preloaded) for each
    # `(run_type, identifier)` in the universe — lets the facade build the rich
    # quarantine summary embedded on each BaselineEntry. Membership doubles as
    # the "is_quarantined" signal — no separate set needed.
    active_quarantines_by_key: dict[tuple[str, str], QuarantinedIdentifier]
    # Stability signals keyed by `(run_type, identifier)` because the same
    # identifier in different run types is a different baseline; merging would
    # bleed storybook stability into playwright stability.
    change_count_by_key: dict[tuple[str, str], int]
    recent_drift_by_key: dict[tuple[str, str], float]
    totals_all: int
    totals_recent: int
    totals_frequent: int
    totals_quarantined: int
    by_run_type: dict[str, int]
    truncated: bool
    generated_at: datetime
