"""``get_run_results`` — read-back of per-metric results for a specific run, through ``MetricResultStore.for_run``
(no FK on ExperimentMetricResult; the store finds a run's rows from the job row and the current metric config).
"""

from collections.abc import Iterable, Mapping
from datetime import timedelta
from typing import Any

from django.utils import timezone

from posthog.dataclasses import frozen
from posthog.models.scoping import team_scope

from products.experiments.backend.hogql_queries.base_query_utils import experiment_window_end
from products.experiments.backend.metric_calculation.config import MetricCalculationConfig, build_calculation_configs
from products.experiments.backend.metric_calculation.results import MetricResultStore, result_configuration_status
from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentMetricResult,
    ExperimentMetricsRecalculation,
)
from products.experiments.backend.result_serialization import strip_step_sessions
from products.experiments.backend.temporal.models import RECALCULATION_WINDOW_TOO_LONG_ERROR_TYPE

from . import query_progress

# A daily timeseries point older than this no longer stands in for a recalculation on the cold-start read. The
# daily run happens once per day, so a fresh experiment always has a point inside the bound.
TIMESERIES_FALLBACK_MAX_AGE = timedelta(hours=24)

# The field of a run's `metric_errors` or `metric_retries` entry that holds the calculation key of the config that
# wrote the entry. Server-side readers use it, `entries_of_current_configs` among them, and no response includes it.
RUN_ENTRY_CALCULATION_KEY = "calculation_key"

RUN_ENTRY_HIDDEN_MESSAGE = (
    "The details of this error aren't available. Recalculate the results to see the current error."
)

# The writers of these steps and error types store only text that PostHog wrote: the rejection of a request, the
# failures to find the experiment or the metric, and the errors of the statistics. Every other writer can store the
# text of a query error, which can name a warehouse table or column.
_FIXED_TEXT_RUN_ENTRY_STEPS = ("request", "discovery")

_FIXED_TEXT_RUN_ENTRY_ERROR_TYPES = ("insufficient_data",)


def entries_of_current_configs(entries: object, configs: Iterable[MetricCalculationConfig]) -> dict[str, Any]:
    """The entries of a run's `metric_errors` or `metric_retries` that a current config of their metric wrote, without
    their calculation key. A stored value that isn't a dict has no entries.

    The entries are keyed by metric uuid, which stays the same when the metric or the exposure criteria change. The
    calculation key hashes both, and with them the warehouse connection that the calculation read. A reader's
    connection access is checked against the current config only. So an entry stays in only when the current config
    gives its key in some key version, the rule by which `get_run_results` finds the result rows. An entry written
    before a key version change stays in, and an entry of an earlier config stays out. A change to a team setting that
    the key hashes also takes the entry out.

    An entry without a calculation key has no config to check. Runs stored before entries had the key hold such
    entries, and so do the writers without a metric config, which store None. The entry stays in, so its metric still
    counts as failed. Its message stays only when its step or error type is one whose writers store fixed text, and is
    `RUN_ENTRY_HIDDEN_MESSAGE` otherwise. A stored entry that isn't a dict counts as an empty entry without a
    calculation key.
    """
    if not isinstance(entries, dict):
        return {}
    configs_by_metric: dict[str, list[MetricCalculationConfig]] = {}
    for calculation_config in configs:
        configs_by_metric.setdefault(calculation_config.metric_id, []).append(calculation_config)
    current: dict[str, Any] = {}
    for metric_uuid, stored in entries.items():
        stored_entry = stored if isinstance(stored, dict) else {}
        calculation_key = stored_entry.get(RUN_ENTRY_CALCULATION_KEY)
        entry = {name: value for name, value in stored_entry.items() if name != RUN_ENTRY_CALCULATION_KEY}
        if calculation_key is not None:
            if any(
                calculation_config.key_version_of(calculation_key) is not None
                for calculation_config in configs_by_metric.get(metric_uuid, [])
            ):
                current[metric_uuid] = entry
        elif (
            entry.get("step") in _FIXED_TEXT_RUN_ENTRY_STEPS
            or entry.get("error_type") in _FIXED_TEXT_RUN_ENTRY_ERROR_TYPES
        ):
            current[metric_uuid] = entry
        else:
            current[metric_uuid] = {**entry, "message": RUN_ENTRY_HIDDEN_MESSAGE}
    return current


@frozen
class RunMetricCounts:
    completed_metrics: int
    failed_metrics: int


def derive_counters(results: list[dict], metric_errors: Mapping[str, Any]) -> RunMetricCounts:
    """Counters are not stored on the row (PR1 contract): they're derived on read from result rows + errors.

    `failed_metrics`    = metrics with an ExperimentMetricResult row with status=FAILED or a `metric_errors` entry.
                          A failed attempt keeps the completed row that held its window, so the entry is what records
                          the failure. A rejected run carries the rows of the run before it, so its error counts only
                          for a metric without a row.
    `completed_metrics` = metrics with an ExperimentMetricResult row with status=COMPLETED that did not fail.

    `results` are rows in the shape of `get_run_results`. `metric_errors` are the entries that the caller serves, so
    `failed_metrics` counts the same entries.

    Inherits the fingerprint-divergence hazard from `get_run_results`: `completed_metrics` can silently drop
    if settings that feed the calculation key change between the workflow's writes and this read.
    `failed_metrics` is partly immune because discovery-step failures come from `metric_errors` (stored on the
    row), not from result rows.
    """
    status_by_uuid = {r["metric_uuid"]: r["status"] for r in results}
    failed = {uuid for uuid, status in status_by_uuid.items() if status == ExperimentMetricResult.Status.FAILED}
    for uuid, error in metric_errors.items():
        rejected = isinstance(error, dict) and error.get("error_type") == RECALCULATION_WINDOW_TOO_LONG_ERROR_TYPE
        if not (rejected and uuid in status_by_uuid):
            failed.add(uuid)
    completed = sum(
        1
        for uuid, status in status_by_uuid.items()
        if status == ExperimentMetricResult.Status.COMPLETED and uuid not in failed
    )
    return RunMetricCounts(completed_metrics=completed, failed_metrics=len(failed))


def build_job_payload(
    recalc: ExperimentMetricsRecalculation,
    *,
    is_existing: bool | None = None,
    include_results: bool = False,
    include_live_progress: bool = False,
) -> dict:
    """Shape a recalc row + derived counters as a dict the serializer can re-serialize.

    Returns model-native values (datetimes, ints, dicts) — DRF handles the wire format. The POST path passes
    `is_existing` to signal whether the workflow needs starting; the GET paths set `include_results` to add the
    result rows that the derived counters read.

    `include_live_progress` opts the caller into one system.processes read per call (see get_live_query_progress);
    the poll (GET) path sets it so an in-flight run carries live ClickHouse progress, while the POST path does not
    (nothing is running yet).

    `metric_errors` and `metric_retries` hold only the entries of the current metric configs, as
    `entries_of_current_configs` defines them, and `failed_metrics` counts those entries. One set of configs selects
    both the result rows and the entries.
    """
    configs = build_calculation_configs(recalc.experiment)
    results = get_run_results(recalc, configs=configs)
    metric_errors = entries_of_current_configs(recalc.metric_errors, configs)
    counts = derive_counters(results, metric_errors)
    payload: dict = {
        "id": str(recalc.id),
        "experiment_id": recalc.experiment_id,
        "status": recalc.status,
        "total_metrics": recalc.total_metrics,
        "completed_metrics": counts.completed_metrics,
        "failed_metrics": counts.failed_metrics,
        "metric_errors": metric_errors,
        "metric_retries": entries_of_current_configs(recalc.metric_retries, configs),
        "trigger": recalc.trigger,
        "created_at": recalc.created_at,
        "started_at": recalc.started_at,
        "completed_at": recalc.completed_at,
        "query_to": recalc.query_to,
    }
    if is_existing is not None:
        payload["is_existing"] = is_existing
    if include_results:
        payload["results"] = results
    if include_live_progress:
        live_progress = query_progress.get_live_query_progress(recalc)
        if live_progress is not None:
            payload.update(live_progress)
    return payload


def get_run_results(
    recalc: ExperimentMetricsRecalculation, *, configs: list[MetricCalculationConfig] | None = None
) -> list[dict]:
    """Return the ExperimentMetricResult rows that belong to THIS run.

    Never returns rows from a previous run or from the timeseries workflow (which uses config fingerprints).

    Ended experiments retain completed rows with a compatible display key after project settings change, without
    making those rows reusable.
    """
    if configs is None:
        configs = build_calculation_configs(recalc.experiment)
    by_uuid = {config.metric_id: config for config in configs}
    rows = MetricResultStore(experiment_id=recalc.experiment_id).for_run(recalc, configs=configs)
    return [
        {
            "metric_uuid": row.metric_uuid,
            "status": row.status,
            "result": strip_step_sessions(row.result),
            "error_message": row.error_message,
            "configuration_status": result_configuration_status(row.fingerprint, by_uuid[row.metric_uuid]),
        }
        for row in rows
    ]


def build_timeseries_cold_start_payload(experiment: Experiment) -> dict | None:
    """Synthetic 'completed' recalculation payload built from each metric's latest completed timeseries point.

    Pure read. Used by GET /metrics_recalculation/latest as a cold-start placeholder when no real
    metrics-recalculation run exists yet. Timeseries rows live in ExperimentMetricResult under the metric's
    CONFIG fingerprint (not a per-run recalc fingerprint), so they're found without any recalc row.

    Only points younger than TIMESERIES_FALLBACK_MAX_AGE count, except that an ended experiment keeps its latest
    compatible point from any time since launch, including a result under earlier settings, when that point reaches
    the end date. The frontend
    accepts a fallback that covers every metric without starting a run, so an older point must read as a gap or
    the page would show weeks-old numbers as completed. Returns None when no metric has a fresh completed point
    (caller then keeps the 404). query_to and completed_at both pin to the freshest point's date. GET never triggers anything itself.
    """
    with team_scope(experiment.team_id, canonical=True):
        calculation_configs = build_calculation_configs(experiment)
        store = MetricResultStore(experiment_id=experiment.id)
        now = timezone.now()
        results: list[dict] = []
        latest_query_to = None
        for calculation_config in calculation_configs:
            # Bounded on both sides: the backfill writes end-of-day points, so today's point can carry a future
            # query_to that would surface here as a future completion time.
            row = None
            if experiment.is_stopped and experiment.start_date:
                row = store.latest_daily_point(
                    calculation_config, since=experiment.start_date, until=now, preserve_history=True
                )
                # A point whose data ends before the end date misses the final hours, so a run must compute them.
                # A backfill stamps the end of its day as query_to, but its data ends at completed_at.
                if row is not None:
                    data_until = min(row.query_to, row.completed_at or row.query_to)
                    if data_until < experiment_window_end(experiment, now):
                        row = None
            if row is None:
                row = store.latest_daily_point(calculation_config, since=now - TIMESERIES_FALLBACK_MAX_AGE, until=now)
            if row is None:
                continue
            results.append(
                {
                    "metric_uuid": row.metric_uuid,
                    "status": row.status,
                    "result": strip_step_sessions(row.result),
                    "error_message": None,
                    "configuration_status": result_configuration_status(row.fingerprint, calculation_config),
                }
            )
            if latest_query_to is None or row.query_to > latest_query_to:
                latest_query_to = row.query_to

        if not results:
            return None

        return {
            "id": "timeseries-fallback",
            "experiment_id": experiment.id,
            "status": ExperimentMetricsRecalculation.Status.COMPLETED,
            "total_metrics": len(calculation_configs),
            "completed_metrics": len(results),
            "failed_metrics": 0,
            "metric_errors": {},
            "metric_retries": {},
            "created_at": latest_query_to,
            "started_at": latest_query_to,
            "completed_at": latest_query_to,
            "query_to": latest_query_to,
            "results": results,
            "result_source": "timeseries_fallback",
        }
