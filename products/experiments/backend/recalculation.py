"""Service layer for experiment metrics recalculation.

Module-level free functions (not methods on ExperimentService) so the API view can compose them directly:

- ``request_recalculation`` — idempotent create: returns the active run if one exists, else creates a pending job.
- ``get_latest_recalculation`` — most recent recalc row for an experiment, or ``None``.
- ``get_run_results`` — read-back of per-metric results for a specific run, through ``MetricResultStore.for_run``
  (no FK on ExperimentMetricResult; the store finds a run's rows from the job row and the current metric config).
"""

import asyncio
from datetime import timedelta
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from prometheus_client import Counter
from rest_framework.exceptions import ValidationError

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Feature, Product, tags_context
from posthog.exceptions_capture import capture_exception
from posthog.models.scoping import get_current_team_id, team_scope
from posthog.models.user import User
from posthog.settings import CLICKHOUSE_CLUSTER
from posthog.temporal.common.client import sync_connect

from products.experiments.backend.metric_calculation.results import MetricResultStore
from products.experiments.backend.metric_calculation.spec import plan
from products.experiments.backend.models.experiment import (
    Experiment,
    ExperimentMetricResult,
    ExperimentMetricsRecalculation,
)
from products.experiments.backend.result_serialization import strip_step_sessions
from products.experiments.backend.temporal.models import (
    METRICS_RECALCULATION_WORKFLOW_NAME,
    ExperimentMetricsRecalculationWorkflowInputs,
)
from products.experiments.backend.temporal.recalculation_logic import discover_experiment_metrics

# How long an active (PENDING/IN_PROGRESS) row blocks new recalculations. Beyond this, the row is treated as
# stale and a fresh recalc is allowed. Sized to be safely above the workflow's worst-case end-to-end runtime
# (discovery retries + per-metric calc retries + progress activities) so a legitimately-slow run can finish
# without being clobbered, but tight enough that an operator can recover within an hour if the workflow
# never started (Temporal connect failure, transient infra issue, etc.). See the rollback in
# start_metrics_recalculation_workflow for the happy-path failure handling; this TTL is the defense-in-depth
# backstop if that rollback itself fails.
_STALE_RECALC_THRESHOLD = timedelta(minutes=30)

# A daily timeseries point older than this no longer stands in for a recalculation on the cold-start read. The
# daily run happens once per day, so a fresh experiment always has a point inside the bound.
TIMESERIES_FALLBACK_MAX_AGE = timedelta(hours=24)

# `is_existing=True` reuse path — counts how often the idempotency guard saves us a workflow start.
# A sustained climb here without a matching climb in requests is the signal the frontend is double-posting.
_recalculation_reuse_counter = Counter(
    "experiment_metrics_recalculation_existing_run_reused",
    "POST requests that returned an existing active run instead of creating a new one (idempotent reuse).",
)
# Fires whenever the 30-min staleness threshold marks a PENDING/IN_PROGRESS row FAILED so the experiment
# can recalculate again. A sustained climb is a leading indicator of Temporal connect failures or the
# rollback in start_metrics_recalculation_workflow itself failing.
_recalculation_stale_cleanup_counter = Counter(
    "experiment_metrics_recalculation_stale_rows_cleaned",
    "Stale recalc rows force-failed to release the per-experiment uniqueness constraint.",
)


def _derive_counters(recalc: ExperimentMetricsRecalculation, results: list[dict] | None = None) -> tuple[int, int]:
    """Counters are not stored on the row (PR1 contract): they're derived on read from result rows + errors.

    `completed_metrics` = ExperimentMetricResult rows with status=COMPLETED for this run's fingerprints.
    `failed_metrics`    = ExperimentMetricResult rows with status=FAILED + metric_errors keys that never made
                          it to a result row (discovery-step failures).

    Accepts an optional pre-computed `results` list to avoid recomputing fingerprints on the GET path where
    the same list is also surfaced to the client.

    Inherits the fingerprint-divergence hazard from `get_run_results`: `completed_metrics` can silently drop
    if settings that feed the calculation key change between the workflow's writes and this read.
    `failed_metrics` is partly immune because discovery-step failures come from `metric_errors` (stored on the
    row), not from result rows.
    """
    rows = results if results is not None else get_run_results(recalc)
    completed = sum(1 for r in rows if r["status"] == ExperimentMetricResult.Status.COMPLETED)
    failed_in_rows = sum(1 for r in rows if r["status"] == ExperimentMetricResult.Status.FAILED)
    uuids_with_row = {r["metric_uuid"] for r in rows}
    discovery_only_failures = sum(1 for uuid in (recalc.metric_errors or {}) if uuid not in uuids_with_row)
    return completed, failed_in_rows + discovery_only_failures


def get_live_query_progress(recalc: ExperimentMetricsRecalculation) -> dict | None:
    """Cumulative ClickHouse progress for an in-flight run: in-flight queries from system.processes plus
    queries already finished during the run from system.query_log, matched by query_id prefix.

    Returns None unless the run is IN_PROGRESS. No storage needed: each metric query is tagged with the
    deterministic client_query_id `experiment_metric_recalc_{recalc_id}_{metric_uuid}_attempt{attempt:02d}`,
    which ClickHouse stamps into query_id as `{team_id}_{client_query_id}_{random}`. The prefix matched below
    stops at the recalc id, so the metric and attempt suffixes do not affect it. system.processes only holds a query
    while it executes, and the metric queries are usually shorter than the poll interval, so processes
    alone reads zero for most of the run; the query_log branch keeps finished queries counted, making
    rows_read cumulative and roughly monotonic across the run (modulo query_log flush lag).

    `estimated_rows_total` is ClickHouse's own total_rows_approx for in-flight queries (revised upward
    mid-scan) plus the final read_rows of finished ones, so it can trail rows_read; treat rows_read as
    the primary signal. Temporal retries of a metric produce one query_log row per attempt and each attempt's
    rows are summed; that overcount is accepted for a decorative counter.
    """
    if recalc.status != ExperimentMetricsRecalculation.Status.IN_PROGRESS:
        return None

    # system.processes and system.query_log are cluster-global tables with no ClickHouse-side tenant scoping:
    # the team boundary is enforced only by the leading `{team_id}_` in the query_id prefix. Callers must pass
    # a request-scoped row (see get_recalculation_by_id); this is the defense-in-depth check that keeps a
    # future unscoped caller from summing another team's queries.
    if recalc.team_id != get_current_team_id():
        return None

    prefix = f"{recalc.team_id}_experiment_metric_recalc_{recalc.id}_%"
    # The prefix alone scopes rows to this run; the time bound exists so the query_log scan prunes to the
    # run's window instead of walking the whole table on every poll. The 60s pad absorbs clock skew between
    # the Django clock that stamped started_at and the ClickHouse clock behind event_time.
    since = (recalc.started_at or recalc.created_at) - timedelta(seconds=60)
    try:
        with tags_context(product=Product.EXPERIMENTS, feature=Feature.CACHE_WARMUP, team_id=recalc.team_id):
            rows = sync_execute(
                """
                SELECT
                    sum(rows_read) AS rows_read,
                    sum(estimated_rows_total) AS estimated_rows_total
                FROM
                (
                    SELECT
                        read_rows AS rows_read,
                        total_rows_approx AS estimated_rows_total
                    FROM clusterAllReplicas(%(cluster)s, system.processes)
                    WHERE query_id LIKE %(prefix)s
                    UNION ALL
                    SELECT
                        read_rows AS rows_read,
                        read_rows AS estimated_rows_total
                    FROM clusterAllReplicas(%(cluster)s, system.query_log)
                    WHERE query_id LIKE %(prefix)s
                        AND type = 'QueryFinish'
                        AND event_date >= toDate(toDateTime(%(since)s))
                        AND event_time >= toDateTime(%(since)s)
                )
                SETTINGS skip_unavailable_shards=1, max_execution_time=2
                """,
                {"cluster": CLICKHOUSE_CLUSTER, "prefix": prefix, "since": int(since.timestamp())},
                workload=Workload.ONLINE,
                team_id=recalc.team_id,
            )
    except Exception:
        # Best-effort, decorative read on the poll's hot path: a cluster hiccup here must never sink the core
        # recalculation payload (status + derived counters). Swallow, and let the run's live progress read null.
        capture_exception()
        return None

    rows_read, estimated_rows_total = rows[0]
    # All-zeros is a real, non-terminal state (queries not started yet, or finished but not flushed to
    # query_log), distinct from "run finished". Return the zeros so the poll can tell "in-flight, nothing
    # visible yet" from terminal null.
    return {
        "rows_read": int(rows_read or 0),
        "estimated_rows_total": int(estimated_rows_total or 0),
    }


def build_job_payload(
    recalc: ExperimentMetricsRecalculation,
    *,
    is_existing: bool | None = None,
    results: list[dict] | None = None,
    include_live_progress: bool = False,
) -> dict:
    """Shape a recalc row + derived counters as a dict the serializer can re-serialize.

    Returns model-native values (datetimes, ints, dicts) — DRF handles the wire format. The POST path passes
    `is_existing` to signal whether the workflow needs starting; the GET paths pass `results` so the same row
    list backs both the derived counters and the response's `results` field (no duplicate fingerprint work).

    `include_live_progress` opts the caller into one system.processes read per call (see get_live_query_progress);
    the poll (GET) path sets it so an in-flight run carries live ClickHouse progress, while the POST path does not
    (nothing is running yet).
    """
    completed_metrics, failed_metrics = _derive_counters(recalc, results=results)
    payload: dict = {
        "id": str(recalc.id),
        "experiment_id": recalc.experiment_id,
        "status": recalc.status,
        "total_metrics": recalc.total_metrics,
        "completed_metrics": completed_metrics,
        "failed_metrics": failed_metrics,
        "metric_errors": recalc.metric_errors,
        "metric_retries": recalc.metric_retries,
        "trigger": recalc.trigger,
        "created_at": recalc.created_at,
        "started_at": recalc.started_at,
        "completed_at": recalc.completed_at,
        "query_to": recalc.query_to,
    }
    if is_existing is not None:
        payload["is_existing"] = is_existing
    if include_live_progress:
        live_progress = get_live_query_progress(recalc)
        if live_progress is not None:
            payload.update(live_progress)
    return payload


def metrics_recalculation_workflow_id(recalculation_id: str) -> str:
    """Temporal workflow id of a recalculation run. The start, the cancel and the admin's Temporal link all
    find a running workflow by this id, so a format change orphans the workflows that are already running."""
    return f"experiment-metrics-recalculation-{recalculation_id}"


def cancel_recalculation_workflow(recalculation_id: str) -> None:
    """Best-effort cancel of a single recalc's Temporal workflow. Swallows failures (already-finished or
    never-started runs) so callers can pair it with a status write without the cancel masking that write."""
    _cancel_superseded_workflows([recalculation_id])


def start_metrics_recalculation_workflow(recalculation_id: str, *, team_id: int, organization_id: str) -> None:
    """Dispatch the recalculation Temporal workflow for a row that request_recalculation just created.

    Start every recalculation workflow through this function, so the workflow name and id, the task queue,
    the org-scoped fairness key and the rollback stay in one place. If the start fails, the row is marked
    FAILED when it is safe to do so, and the exception propagates to the caller.
    """
    try:
        temporal = sync_connect()
        asyncio.run(
            temporal.start_workflow(
                METRICS_RECALCULATION_WORKFLOW_NAME,
                ExperimentMetricsRecalculationWorkflowInputs(
                    recalculation_id=recalculation_id,
                    fairness_key=organization_id,
                ),
                id=metrics_recalculation_workflow_id(recalculation_id),
                task_queue=settings.EXPERIMENTS_RECALCULATION_TASK_QUEUE,
            )
        )
    except Exception:
        # team-scoped filter: defense in depth so the rollback can never reach across teams even if
        # recalculation_id were ever sourced from somewhere less trusted than the row we just created.
        # start_workflow can raise after the server accepted the start (e.g. RPC deadline on the
        # response leg), so only roll back a row that is still PENDING with no query_to. A row past
        # mark_started belongs to its running workflow and proceeds untouched. In the narrow window
        # where only discovery ran, the rollback wins deliberately: the mark_started and
        # mark_completed guards then terminate that orphan cleanly, and the caller's retry (a new
        # POST, or the admin action again) starts the replacement.
        ExperimentMetricsRecalculation.objects.for_team(team_id).filter(
            id=recalculation_id,
            status=ExperimentMetricsRecalculation.Status.PENDING,
            query_to__isnull=True,
        ).update(status=ExperimentMetricsRecalculation.Status.FAILED)
        raise


def _cancel_superseded_workflows(recalculation_ids: list[str]) -> None:
    """Best-effort cancellation of workflows whose rows were force-failed by the staleness cleanup."""
    try:
        temporal = sync_connect()
    except Exception as e:
        capture_exception(e)
        return
    for recalculation_id in recalculation_ids:
        try:
            handle = temporal.get_workflow_handle(metrics_recalculation_workflow_id(recalculation_id))
            asyncio.run(handle.cancel())
        except Exception:
            # Expected for rows whose workflow never started (Temporal connect failure) or already finished.
            pass


def request_recalculation(experiment: Experiment, user: User | None, trigger: str = "manual") -> dict:
    """Create an idempotent batch recalculation request for all experiment metrics.

    If an active (pending or in_progress) run already exists for this experiment, returns the existing run's
    serialized payload with ``is_existing=True`` — the caller should NOT start a new workflow in that case.
    Otherwise creates a fresh pending row.
    """
    if not experiment.is_launched:
        raise ValidationError("Cannot recalculate metrics for experiment that hasn't started")

    with team_scope(experiment.team_id, canonical=True), transaction.atomic():
        # Serialize concurrent POSTs for this experiment by locking the Experiment row up front. Without this,
        # two simultaneous POSTs (double-click, retry storm, two tabs) both see no active recalc row and both
        # reach .create(); the second hits the unique_active_metrics_recalculation_per_experiment constraint
        # and returns HTTP 500. Locking the Experiment row queues the second POST behind the first, which
        # then sees the freshly-created row in its lookup and returns is_existing=True cleanly.
        Experiment.objects.select_for_update().filter(id=experiment.id).first()

        # Activity-aware staleness: PENDING rows anchor on created_at (workflow never reached its start
        # activity); IN_PROGRESS rows anchor on started_at (workflow began executing then stalled). A row past
        # the threshold is treated as dead and skipped, so a fresh recalc can start. Without this, a PENDING
        # row left orphaned by a Temporal-connect failure that also lost its rollback UPDATE would permanently
        # lock the experiment out of recalculations.
        threshold = timezone.now() - _STALE_RECALC_THRESHOLD
        existing = (
            ExperimentMetricsRecalculation.objects.filter(experiment=experiment)
            .filter(
                Q(status=ExperimentMetricsRecalculation.Status.PENDING, created_at__gte=threshold)
                | Q(status=ExperimentMetricsRecalculation.Status.IN_PROGRESS, started_at__gte=threshold)
            )
            .first()
        )
        if existing:
            _recalculation_reuse_counter.inc()
            return build_job_payload(existing, is_existing=True)

        # No fresh active row, but stale tombstones might still hold the per-experiment uniqueness constraint
        # (unique_active_metrics_recalculation_per_experiment). Mark them FAILED so the constraint releases
        # and the new row can land, and cancel their workflows after commit — a superseded run that is still
        # executing would otherwise keep burning worker slots and ClickHouse quota alongside its replacement.
        stale_ids = list(
            ExperimentMetricsRecalculation.objects.filter(
                experiment=experiment,
                status__in=[
                    ExperimentMetricsRecalculation.Status.PENDING,
                    ExperimentMetricsRecalculation.Status.IN_PROGRESS,
                ],
            ).values_list("id", flat=True)
        )
        if stale_ids:
            # No completed_at: that stamp is reserved for the workflow finalize step, and its absence is
            # what keeps superseded/tombstone rows out of get_latest_recalculation.
            ExperimentMetricsRecalculation.objects.filter(
                team=experiment.team, experiment=experiment, id__in=stale_ids
            ).update(status=ExperimentMetricsRecalculation.Status.FAILED)
            _recalculation_stale_cleanup_counter.inc(len(stale_ids))
            transaction.on_commit(lambda: _cancel_superseded_workflows([str(stale_id) for stale_id in stale_ids]))

        # Set total_metrics up front from the experiment definition so the client can show progress
        # ("N of M") immediately, before the workflow's discovery activity confirms the same count.
        metrics = discover_experiment_metrics(experiment)
        recalc = ExperimentMetricsRecalculation.objects.create(
            team=experiment.team,
            experiment=experiment,
            trigger=trigger,
            status=ExperimentMetricsRecalculation.Status.PENDING,
            created_by=user,
            total_metrics=len(metrics),
            metric_uuids=[m.metric_uuid for m in metrics],
        )
        return build_job_payload(recalc, is_existing=False)


def get_active_recalculation(experiment: Experiment) -> ExperimentMetricsRecalculation | None:
    with team_scope(experiment.team_id, canonical=True):
        threshold = timezone.now() - _STALE_RECALC_THRESHOLD
        return (
            ExperimentMetricsRecalculation.objects.filter(team=experiment.team, experiment=experiment)
            .filter(
                Q(status=ExperimentMetricsRecalculation.Status.PENDING, created_at__gte=threshold)
                | Q(status=ExperimentMetricsRecalculation.Status.IN_PROGRESS, started_at__gte=threshold)
            )
            .order_by("-created_at")
            .first()
        )


def get_latest_recalculation(experiment: Experiment) -> ExperimentMetricsRecalculation | None:
    with team_scope(experiment.team_id, canonical=True):
        return (
            ExperimentMetricsRecalculation.objects.filter(team=experiment.team, experiment=experiment)
            .filter(
                # completed_at is only ever stamped by the workflow's finalize step, so it separates runs
                # that really finished from trigger-failure tombstones (status flipped to FAILED at create
                # time, never started). Keying on metric_errors instead would hide a failed run whose
                # failures live only in result rows.
                Q(status=ExperimentMetricsRecalculation.Status.COMPLETED)
                | (Q(status=ExperimentMetricsRecalculation.Status.FAILED) & Q(completed_at__isnull=False))
            )
            .order_by("-created_at")
            .first()
        )


def get_recalculation_by_id(experiment: Experiment, recalculation_id: str) -> ExperimentMetricsRecalculation | None:
    """Return the recalculation row for ``recalculation_id`` if it belongs to ``experiment``, else None.

    Enforces experiment scoping so the id-based GET cannot leak rows from a different experiment in the same team.
    Returns None for a malformed UUID rather than raising, so the calling view can answer with a clean 404.
    """
    try:
        uuid_value = UUID(recalculation_id)
    except (ValueError, TypeError):
        return None
    with team_scope(experiment.team_id, canonical=True):
        return ExperimentMetricsRecalculation.objects.filter(
            team=experiment.team, experiment=experiment, id=uuid_value
        ).first()


def get_run_results(recalc: ExperimentMetricsRecalculation) -> list[dict]:
    """Return the ExperimentMetricResult rows that belong to THIS run.

    Never returns rows from a previous run or from the timeseries workflow (which uses config fingerprints).

    Divergence hazard: the store finds a run's rows by recomputing each metric's fingerprint from the current
    calculation spec (start date, exposure criteria, stats and CUPED settings, baseline, variants, test account
    filters, maturity). If any of these change after the run wrote its rows, this can return [] for what is on-disk
    a successful run, until the settings revert. Symptom: "results disappeared after editing the experiment."
    This is the explicit trade-off of "no FK on ExperimentMetricResult": the snapshot lives in the fingerprint, not
    in a stored column.

    A run from before calculation key version 2 is read through the metrics' legacy keys, and each such result
    carries `legacy: True`.
    """
    stored = MetricResultStore(experiment_id=recalc.experiment_id).for_run(recalc)
    return [
        {
            "metric_uuid": item.row.metric_uuid,
            "status": item.row.status,
            "result": strip_step_sessions(item.row.result),
            "error_message": item.row.error_message,
            "legacy": item.legacy,
        }
        for item in stored
    ]


def build_timeseries_cold_start_payload(experiment: Experiment) -> dict | None:
    """Synthetic 'completed' recalculation payload built from each metric's latest completed timeseries point.

    Pure read. Used by GET /metrics_recalculation/latest as a cold-start placeholder when no real
    metrics-recalculation run exists yet. Timeseries rows live in ExperimentMetricResult under the metric's
    CONFIG fingerprint (not a per-run recalc fingerprint), so they're found without any recalc row.

    Only points younger than TIMESERIES_FALLBACK_MAX_AGE count. The frontend accepts a fallback that covers every
    metric without starting a run, so an older point must read as a gap or the page would show weeks-old numbers
    as completed. Returns None when no metric has a fresh completed point (caller then keeps the 404). query_to
    and completed_at both pin to the freshest point's date. GET never triggers anything itself.
    """
    with team_scope(experiment.team_id, canonical=True):
        specs = plan(experiment)
        store = MetricResultStore(experiment_id=experiment.id)
        now = timezone.now()
        results: list[dict] = []
        latest_query_to = None
        for spec in specs:
            # Bounded on both sides: the backfill writes end-of-day points, so today's point can carry a future
            # query_to that would surface here as a future completion time.
            stored = store.latest_daily_point(
                spec, since=now - TIMESERIES_FALLBACK_MAX_AGE, until=now, include_legacy=True
            )
            if stored is None:
                continue
            row = stored.row
            results.append(
                {
                    "metric_uuid": row.metric_uuid,
                    "status": row.status,
                    "result": strip_step_sessions(row.result),
                    "error_message": None,
                    "legacy": stored.legacy,
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
            "total_metrics": len(specs),
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
