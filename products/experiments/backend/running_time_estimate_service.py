"""Service layer for the running-time estimate list endpoint.

Composes the pure math in ``running_time_calculator`` with a cheap Postgres read of the latest
metric result and a short-lived cache. Automatic mode reads the sizing metric's latest completed
``ExperimentMetricResult`` blob; manual mode needs no read. Never runs a ClickHouse query.
"""

import hashlib
from datetime import datetime

from django.utils import timezone

from posthog.utils import get_safe_cache, safe_cache_set

from products.experiments.backend.hogql_queries.experiment_metric_fingerprint import compute_metric_fingerprint
from products.experiments.backend.hogql_queries.utils import get_experiment_stats_method
from products.experiments.backend.models.experiment import Experiment, ExperimentMetricResult
from products.experiments.backend.result_serialization import strip_step_sessions
from products.experiments.backend.running_time_calculator import (
    RunningTimeEstimate,
    estimate_running_time_for_experiment,
    select_sizing_metric,
)

# Bump when the cached value's shape changes; pickled values would otherwise deserialize stale-shaped.
_CACHE_VERSION = "v1"
CACHE_TTL_SECONDS = 15 * 60


def _latest_completed_result_blob(experiment: Experiment, metric: dict) -> dict | None:
    """Latest completed timeseries result for one metric, under its config fingerprint.

    Mirrors the read in ``build_timeseries_cold_start_payload`` but scoped to a single metric.
    """
    config_fingerprint = compute_metric_fingerprint(
        metric,
        experiment.start_date,
        get_experiment_stats_method(experiment),
        experiment.exposure_criteria,
        only_count_matured_users=experiment.only_count_matured_users,
        excluded_variants=experiment.excluded_variants,
    )
    row = (
        ExperimentMetricResult.objects.filter(
            experiment=experiment,
            metric_uuid=metric.get("uuid"),
            fingerprint=config_fingerprint,
            status=ExperimentMetricResult.Status.COMPLETED,
        )
        .order_by("-query_to")
        .first()
    )
    if row is None:
        return None
    return strip_step_sessions(row.result)


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
    exposure_config = config.get("exposure_estimate_config") or {}
    is_manual = exposure_config.get("conversionRateInputType") == "manual"

    result_blob: dict | None = None
    query_to = None
    if not is_manual:
        selected = select_sizing_metric(experiment.metrics, experiment.primary_metrics_ordered_uuids)
        if selected is not None:
            metric, _ = selected
            result_blob = _latest_completed_result_blob(experiment, metric)
            if result_blob is not None:
                query_to = result_blob.get("query_to")

    cache_key = _cache_key(experiment, query_to)
    cached = get_safe_cache(cache_key)
    if isinstance(cached, RunningTimeEstimate):
        return cached

    estimate = estimate_running_time_for_experiment(
        metrics=experiment.metrics,
        primary_metrics_ordered_uuids=experiment.primary_metrics_ordered_uuids,
        running_time_calculation=config,
        start_date=experiment.start_date,
        number_of_variants=_number_of_variants(experiment),
        result_blob=result_blob,
        now=now,
    )
    safe_cache_set(cache_key, estimate, timeout=CACHE_TTL_SECONDS)
    return estimate
