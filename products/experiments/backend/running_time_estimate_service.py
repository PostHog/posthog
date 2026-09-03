"""Service layer for the running-time estimate list endpoint.

Composes the pure math in ``running_time_calculator`` with a cheap Postgres read of the latest
metric result and a short-lived cache. Automatic mode reads the sizing metric's latest completed
``ExperimentMetricResult`` blob; manual mode needs no read. Never runs a ClickHouse query.
"""

import hashlib
from datetime import datetime

from django.utils import timezone

from posthog.models.team.extensions import get_or_create_team_extension
from posthog.utils import get_safe_cache, safe_cache_set

from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig
from products.experiments.backend.recalculation import (
    build_timeseries_cold_start_payload,
    get_latest_recalculation,
    get_run_results,
)
from products.experiments.backend.running_time_calculator import (
    RunningTimeEstimate,
    estimate_running_time_for_experiment,
    resolve_minimum_detectable_effect,
    select_sizing_metric,
)
from products.experiments.backend.temporal.metric_resolution import primary_metric_dicts

# Bump when the cached value's shape changes; pickled values would otherwise deserialize stale-shaped.
_CACHE_VERSION = "v1"
CACHE_TTL_SECONDS = 15 * 60


def _latest_result_blob_for_metric(
    experiment: Experiment, metric_uuid: str | None
) -> tuple[dict | None, datetime | None]:
    """The result blob the detail page shows for one metric and the window it covers, or ``(None, None)``.

    Mirrors the precedence in the ``metrics_recalculation/latest`` endpoint: the latest terminal
    recalculation run first, then the timeseries cold-start payload. Reuses the recalculation module
    so the list reads the exact same source the detail page does. ``query_to`` is the source row's
    window, not part of the blob, so the caller can key its cache on a fresher result.
    """
    if metric_uuid is None:
        return None, None

    recalc = get_latest_recalculation(experiment)
    if recalc is not None:
        results = get_run_results(recalc)
        query_to = recalc.query_to
    else:
        payload = build_timeseries_cold_start_payload(experiment)
        results = payload["results"] if payload is not None else []
        query_to = payload["query_to"] if payload is not None else None

    for entry in results:
        if entry.get("metric_uuid") == metric_uuid and entry.get("status") == "completed":
            return entry.get("result"), query_to
    return None, None


def _number_of_variants(experiment: Experiment) -> int:
    return len(experiment.feature_flag.variants) or 2


def _cache_key(experiment: Experiment, query_to: datetime | None) -> str:
    flag_updated = experiment.feature_flag.updated_at if experiment.feature_flag_id else None
    parts = ":".join(
        value.isoformat() if isinstance(value, datetime) else ""
        for value in (experiment.updated_at, flag_updated, query_to)
    )
    digest = hashlib.sha256(parts.encode()).hexdigest()[:16]
    return f"experiment_running_time_{_CACHE_VERSION}_{experiment.team_id}_{experiment.pk}_{digest}"


def compute_running_time_estimate(experiment: Experiment, now: datetime | None = None) -> RunningTimeEstimate:
    """Estimate for one experiment, reading a cached snapshot when the inputs are unchanged.

    Automatic mode reads the sizing metric's latest completed result; manual mode reads only saved
    config. The cache key folds in the experiment and flag ``updated_at`` and the result window, so an
    edit or a fresher result misses the cache instead of serving stale numbers.
    """
    now = now or timezone.now()
    config = experiment.running_time_calculation or {}

    # Both modes use live exposures for remaining time (manual differs only in using a fixed rate), so
    # read the sizing metric's latest result for either. See estimate_running_time_for_experiment.
    result_blob: dict | None = None
    query_to = None
    # Include saved (shared) primary metrics, not only inline ones, so the sizing metric matches the
    # detail page when a saved metric is the first primary metric.
    selected = select_sizing_metric(primary_metric_dicts(experiment), experiment.primary_metrics_ordered_uuids)
    if selected is not None:
        metric, _ = selected
        result_blob, query_to = _latest_result_blob_for_metric(experiment, metric.get("uuid"))

    cache_key = _cache_key(experiment, query_to)
    cached = get_safe_cache(cache_key)
    if isinstance(cached, RunningTimeEstimate):
        return cached

    # Most experiments never save an MDE; the detail page falls back to the team default, then to 30.
    # Match that here or every such experiment would size to null.
    team_config = get_or_create_team_extension(experiment.team, TeamExperimentsConfig)
    mde = resolve_minimum_detectable_effect(
        config.get("minimum_detectable_effect"), team_config.default_minimum_detectable_effect
    )

    estimate = estimate_running_time_for_experiment(
        metrics=experiment.metrics,
        primary_metrics_ordered_uuids=experiment.primary_metrics_ordered_uuids,
        running_time_calculation=config,
        start_date=experiment.start_date,
        number_of_variants=_number_of_variants(experiment),
        result_blob=result_blob,
        now=now,
        mde_override=mde,
    )
    safe_cache_set(cache_key, estimate, timeout=CACHE_TTL_SECONDS)
    return estimate
