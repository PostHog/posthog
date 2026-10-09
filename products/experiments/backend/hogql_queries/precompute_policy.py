"""
Policy for experiment precomputation: TTL schedule, job width, and the gates that
decide whether a query may use precomputed data at all.

Shared by the experiment query runner, the exposures query runner, and replay linkage.
"""

from datetime import UTC, datetime
from typing import Any, Optional

from django.db.models import Q

from pydantic import BaseModel

from posthog.models.team.team import Team

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationResult,
    LazyComputationTable,
    TtlSchedule,
    ensure_precomputed,
    parse_ttl_schedule,
)
from products.cohorts.backend.models.cohort import Cohort
from products.experiments.backend.hogql_queries.experiment_query_builder import ExperimentQueryBuilder
from products.experiments.backend.hogql_queries.exposure_query_logic import has_activation_config
from products.experiments.backend.hogql_queries.types import PrecomputeSkipReason
from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig

# Variable TTL for experiment exposure lazy computation. Days 2-4 stay
# recomputable (18h, just under the ~24h warmer cadence) so the daily warmer
# folds in late-arriving exposure events before a window freezes. Freezing too
# early keeps a stale first_exposure_time and undercounts the metric window.
DEFAULT_EXPOSURE_TTL_SECONDS = {
    "0d": 15 * 60,  # 15 min
    "1d": 60 * 60,  # 1 hour
    "4d": 18 * 60 * 60,  # 18 hours; covers windows 2-4 days old
    "default": 60 * 24 * 60 * 60,  # 60 days - data frozen
}

# Cap on merged precompute job width. Without it, the frozen band (everything
# older than 4 days, one uniform TTL) merges into a single INSERT, so a cold or
# TTL-expired long-running experiment scans hundreds of days in one query. For
# high-volume teams that deterministically exceeds the per-query bytes-to-read
# cap or the 600s timeout and can never succeed. Seven days keeps the worst
# observed per-day scan rates comfortably under both limits, while creating far
# fewer jobs (and fewer rows per user to re-aggregate at read time) than daily
# chunks. Completed chunks persist, so a wide backfill converges across runs
# instead of failing atomically on every attempt.
PRECOMPUTE_MAX_WINDOW_DAYS = 7

# Spread frozen chunk expiries so an experiment's history does not expire all at once
# (see TtlSchedule.default_ttl_jitter_seconds). 14 days means roughly one chunk expiry
# per day for a months-long experiment; a larger value would only keep data on disk longer.
PRECOMPUTE_TTL_JITTER_SECONDS = 14 * 24 * 60 * 60

# Upper bound on how far past the experiment end a metric-events build may scan.
# retention_window_end is an unrestricted user-supplied integer; without a cap, a huge
# window would stretch the precompute horizon into thousands of daily jobs before the
# executor's timeout check. Past the cap the metric falls back to the direct scan.
METRIC_EVENTS_MAX_WINDOW_EXTENSION_SECONDS = 90 * 24 * 60 * 60  # 90 days


def experiment_precompute_ttl_schedule(team_timezone: str) -> TtlSchedule:
    return parse_ttl_schedule(
        DEFAULT_EXPOSURE_TTL_SECONDS,
        team_timezone,
        max_window_days=PRECOMPUTE_MAX_WINDOW_DAYS,
        default_ttl_jitter_seconds=PRECOMPUTE_TTL_JITTER_SECONDS,
    )


# Minimum experiment runtime before auto-enabling precomputation. The
# today-window TTL (DEFAULT_EXPOSURE_TTL_SECONDS["0d"], 15 min) caches the
# entire current-day result, so for very young experiments freshly arriving
# exposures stay invisible until that TTL elapses. The gate scopes that
# trade-off to experiments where most of the data is already in past
# (frozen) windows. Bypassed by an explicit PrecomputationMode.PRECOMPUTED
# query override.
#
# Why 12h: it covers the workday in which users launch experiments. Users
# refresh the results page most often then, so the 15-min cache lag is most
# noticeable. After that, refreshes drop off and the cost saving from
# precomputation matters more than the freshness gap. 12h is also short enough
# that experiments hit the precomputed (fast) path on day two.
MIN_PRECOMPUTATION_DURATION_SECONDS = 12 * 60 * 60  # 12 hours


def experiment_has_min_runtime_for_precomputation(
    start_date: Optional[datetime],
    end_date: Optional[datetime],
) -> bool:
    """Return True when the experiment has been running for at least
    MIN_PRECOMPUTATION_DURATION_SECONDS.

    For running experiments, elapsed time is measured against now. For
    completed experiments (end_date in the past), the actual run length is
    used. A future end_date (planned end) is ignored so we don't credit
    runtime that hasn't happened yet.

    This is elapsed *runtime*, which is a different concept from the analysis
    window. It clamps to min(now, end_date), which is the opposite of
    experiment_window_end: there a future end_date wins for the query window,
    because no events exist after now. Keep the two rules separate, and do not
    fold this into the window primitive.
    """
    if start_date is None:
        return False
    now = datetime.now(UTC)
    effective_end = end_date if (end_date is not None and end_date <= now) else now
    return (effective_end - start_date).total_seconds() >= MIN_PRECOMPUTATION_DURATION_SECONDS


def _collect_cohort_ids(obj: Any) -> set[int]:
    """Cohort IDs referenced anywhere in a filter/criteria/metric JSON structure."""
    ids: set[int] = set()
    if isinstance(obj, dict):
        if obj.get("type") in ("cohort", "static-cohort", "precalculated-cohort"):
            value = obj.get("value")
            if isinstance(value, int | str):
                try:
                    ids.add(int(value))
                except ValueError:
                    pass
        for nested in obj.values():
            ids |= _collect_cohort_ids(nested)
    elif isinstance(obj, list):
        for item in obj:
            ids |= _collect_cohort_ids(item)
    return ids


def has_uncalculated_cohorts(team: Team, *filter_sources: Any) -> bool:
    """True when any cohort referenced in the given filter structures hasn't finished its
    first materialization (dynamic: no completed version; static: initial population running).

    A query against such a cohort reads its partially-inserted membership. The query succeeds
    but undercounts, with a skew that depends on insertion order. A precompute build in that
    state freezes the torn snapshot for the frozen-band TTL, so precompute must wait until the
    first calculation lands. A cohort with a completed version is safe even mid-recalculation,
    because reads pin the last complete version. Cohorts recalculate frequently, so a gate on
    is_calculating would disable precompute almost permanently.
    """
    ids: set[int] = set()
    for source in filter_sources:
        if source is None:
            continue
        if isinstance(source, BaseModel):
            source = source.model_dump()
        ids |= _collect_cohort_ids(source)
    if not ids:
        return False
    return Cohort.objects.filter(
        Q(is_static=False, version__isnull=True) | Q(is_static=True, is_calculating=True),
        team__project_id=team.project_id,
        pk__in=ids,
        deleted=False,
    ).exists()


# Reasons that mean "do not precompute". The other PrecomputeSkipReason members explain a
# direct-path query that precompute was attempted for, so they must not gate the bool.
BLOCKING_PRECOMPUTE_SKIP_REASONS = frozenset(
    {
        PrecomputeSkipReason.OVERRIDE_DIRECT,
        PrecomputeSkipReason.TEAM_DISABLED,
        PrecomputeSkipReason.MIN_RUNTIME,
        PrecomputeSkipReason.ACTIVATION_CONFIG,
        PrecomputeSkipReason.COHORT_NOT_CALCULATED,
    }
)


def team_precompute_skip_reason(
    team: Team,
    config: TeamExperimentsConfig,
    experiment: Experiment,
    exposure_criteria: Any,
    *cohort_filter_sources: Any,
) -> Optional[PrecomputeSkipReason]:
    """The precompute gates that apply to every experiment query, shared by both runners."""
    if not config.experiment_precomputation_enabled:
        return PrecomputeSkipReason.TEAM_DISABLED
    if not experiment_has_min_runtime_for_precomputation(experiment.start_date, experiment.end_date):
        return PrecomputeSkipReason.MIN_RUNTIME
    # Activation-mode exposures can't be cached per day: the flag→activation ordering
    # crosses bucket boundaries.
    if has_activation_config(exposure_criteria):
        return PrecomputeSkipReason.ACTIVATION_CONFIG
    if has_uncalculated_cohorts(team, exposure_criteria, *cohort_filter_sources):
        return PrecomputeSkipReason.COHORT_NOT_CALCULATED
    return None


def ensure_exposures_precomputed(
    team: Team,
    builder: ExperimentQueryBuilder,
    time_range_start: datetime,
    time_range_end: datetime,
) -> LazyComputationResult:
    query_string, placeholders = builder.get_exposure_query_for_precomputation()

    return ensure_precomputed(
        team=team,
        insert_query=query_string,
        time_range_start=time_range_start,
        time_range_end=time_range_end,
        ttl_seconds=experiment_precompute_ttl_schedule(team.timezone),
        table=LazyComputationTable.EXPERIMENT_EXPOSURES_PREAGGREGATED,
        placeholders=placeholders,
        sentinel_placeholders={"experiment_date_to"},
        end_is_data_horizon=True,
        # High-volume teams' builds OOM even at capped window widths; spilling the
        # GROUP BY to disk degrades gracefully instead of failing the build.
        spill_to_disk=True,
    )
