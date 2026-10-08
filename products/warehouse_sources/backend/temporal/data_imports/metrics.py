import logging
import datetime as dt
from typing import TYPE_CHECKING

from temporalio import activity, workflow
from temporalio.common import MetricCounter, MetricHistogram

from posthog.kafka_client.routing import get_producer
from posthog.kafka_client.topics import KAFKA_APP_METRICS2
from posthog.models.event.util import format_clickhouse_timestamp

from products.warehouse_sources.backend.models.external_data_destination import get_or_create_warehouse_destination

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_job import ExternalDataJob

logger = logging.getLogger(__name__)


DATA_IMPORT_APP_SOURCE = "warehouse_source_sync"

_TERMINAL_STATUS_TO_METRIC: dict[str, tuple[str, str]] = {
    "Completed": ("success", "succeeded"),
    "Failed": ("failure", "failed"),
    "BillingLimitReached": ("failure", "billing_limited"),
    "BillingLimitTooLow": ("failure", "billing_limited"),
}

# Shared source of truth for which ExternalDataJob statuses are terminal — also
# imported by update_external_job_status to gate finished_at stamping and metric
# emission on the first terminal transition.
TERMINAL_JOB_STATUSES: frozenset[str] = frozenset(_TERMINAL_STATUS_TO_METRIC)

# latest_error written when lock takeover force-fails a stuck-RUNNING job; sentinel that
# lets update_external_job_status permit Failed -> Completed for takeover-failed jobs only.
# Shown to the customer verbatim, so keep it plain; the exact string is the recovery sentinel,
# so all comparisons must go through this constant rather than the literal.
LOCK_TAKEOVER_LATEST_ERROR = (
    "A previous sync run did not shut down cleanly and was still marked as running. "
    "PostHog cleaned it up so syncing can continue. No action is needed."
)


def get_data_import_finished_metric(source_type: str | None, status: str) -> MetricCounter:
    source_type = source_type or "unknown"
    return (
        workflow.metric_meter()
        .with_additional_attributes({"source_type": source_type, "status": status})
        .create_counter("data_import_finished", "Number of data imports finished, for any reason (including failure).")
    )


def get_fast_returned_run_metric(source_type: str | None) -> MetricCounter:
    # Separate from `data_import_finished` (which still counts these as completed) so the
    # rollout can be read as a share of runs without double-counting them there.
    return (
        workflow.metric_meter()
        .with_additional_attributes({"source_type": source_type or "unknown"})
        .create_counter("data_import_fast_returned", "Runs completed on a negative source probe, without extracting.")
    )


def get_v3_lock_skipped_metric() -> MetricCounter:
    # A skipped run leaves no job row and no schema-status change; without this
    # counter a schema can silently miss every scheduled slot for days.
    return workflow.metric_meter().create_counter(
        "data_import_v3_lock_skipped", "Scheduled v3 runs skipped because the pipeline lock was not acquired."
    )


def get_version_check_skipped_metric() -> MetricCounter:
    # Same visibility gap as the lock metric: the skip leaves no job row, so a persistently
    # failing version check silently costs a schema every scheduled slot.
    return workflow.metric_meter().create_counter(
        "data_import_version_check_skipped", "Scheduled runs skipped because the pipeline version check failed."
    )


def get_retry_budget_reduced_metric(source_type: str | None) -> MetricCounter:
    # Read against `data_import_finished{status="failed"}`: the two converging means the give-up
    # covers the failures it was built for.
    return (
        workflow.metric_meter()
        .with_additional_attributes({"source_type": source_type or "unknown"})
        .create_counter(
            "data_import_retry_budget_reduced",
            "Runs whose import retry cap was cut because the schema keeps failing.",
        )
    )


def get_run_deferred_metric() -> MetricCounter:
    # Same visibility gap as the lock and version-check metrics: the skip leaves no job row, so
    # without this counter a schema can silently miss every scheduled slot.
    return workflow.metric_meter().create_counter(
        "data_import_run_deferred", "Scheduled runs that stood down because the schema keeps failing."
    )


def get_progressless_stand_down_metric(source_type: str | None) -> MetricCounter:
    # The resumable cap is justified only while attempts continue, and this counts where they did
    # not, so a source that cannot checkpoint at all shows up as a class rather than as a ticket.
    return (
        activity.metric_meter()
        .with_additional_attributes({"source_type": source_type or "unknown"})
        .create_counter(
            "data_import_progressless_stand_down",
            "Imports that stopped retrying because no attempt committed anything to resume from.",
        )
    )


def get_worker_shutdown_handoff_metric(source_type: str | None) -> MetricCounter:
    # Counts imports that gave up a shutting-down worker so another pod can continue them. An
    # import that never hands off keeps its pod alive for the whole graceful shutdown timeout.
    return (
        activity.metric_meter()
        .with_additional_attributes({"source_type": source_type or "unknown"})
        .create_counter(
            "warehouse_worker_shutdown_handoff_total",
            "Imports that raised WorkerShuttingDownError so another worker could continue them.",
        )
    )


def get_import_handoffs_per_run_metric(source_type: str | None) -> MetricHistogram:
    # One observation per workflow run that can hand off for free, zero included. Compare it with
    # the attempt histogram to tell runs that worker restarts moved from runs that failed.
    return (
        workflow.metric_meter()
        .with_additional_attributes({"source_type": source_type or "unknown"})
        .create_histogram(
            "warehouse_import_handoffs_per_run",
            "Worker-shutdown hand-offs of the import activity in one workflow run.",
        )
    )


def emit_data_import_app_metrics(job: "ExternalDataJob") -> None:
    """Emit app_metrics2 rows for a data import job that just reached terminal state.

    Writes best-effort messages to the app_metrics2 Kafka topic — failures are
    logged but never raised, so a broken metrics path cannot surface as a
    pipeline failure. Runs that are not in a terminal status are a no-op.
    """
    kind_name = _TERMINAL_STATUS_TO_METRIC.get(job.status)
    if kind_name is None:
        return

    metric_kind, metric_name = kind_name
    finished_at = job.finished_at or dt.datetime.now(dt.UTC)
    timestamp = format_clickhouse_timestamp(finished_at)
    schema_instance_id = str(job.schema_id) if job.schema_id else ""

    def rows_for(instance_id: str) -> list[dict]:
        common = {
            "team_id": job.team_id,
            "app_source": DATA_IMPORT_APP_SOURCE,
            "app_source_id": str(job.pipeline_id),
            "instance_id": instance_id,
            "timestamp": timestamp,
        }
        emitted = [{**common, "metric_kind": metric_kind, "metric_name": metric_name, "count": 1}]
        if job.rows_synced and job.rows_synced > 0:
            emitted.append({**common, "metric_kind": "rows", "metric_name": "rows_synced", "count": job.rows_synced})
        return emitted

    payloads: list[dict] = rows_for(schema_instance_id)

    # The same metrics again per destination, keyed by "<schema>/<destination>". The metric names
    # stay as they are: they are LowCardinality on a table several products share, so a destination
    # id cannot go in them. `instance_id` is a plain String and already means "which instance of
    # this app source", which is what a destination is here.
    #
    # These are extra rows, not replacements. Everything that filters `instance_id` by a bare
    # schema id matches exactly what it did before and never sees them.
    #
    # Each destination is also keyed on its own, without a schema. A source-level surface wants one
    # series per destination across every table, and the API filters `instance_id` by equality, so
    # without this row it would have to ask once per schema per destination.
    # A run still reaches here with no ids: a job that predates destinations, a CDC companion
    # lane, or a run of a team the flag was off for. Without this fallback those runs report no
    # destination at all, and a project sees a gap in its rows-by-destination chart.
    destination_ids = list(job.destination_ids or [])
    if not destination_ids:
        try:
            destination_ids = [str(get_or_create_warehouse_destination(job.team_id).id)]
        except Exception:
            logger.exception("Failed to resolve the warehouse destination for data import metrics")

    for destination_id in destination_ids:
        payloads.extend(rows_for(f"{schema_instance_id}/{destination_id}"))
        payloads.extend(rows_for(str(destination_id)))

    try:
        producer = get_producer(topic=KAFKA_APP_METRICS2)
        for payload in payloads:
            producer.produce(topic=KAFKA_APP_METRICS2, data=payload)
    except Exception:
        logger.exception("Failed to emit data import app_metrics2 rows")
