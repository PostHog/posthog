from dataclasses import dataclass

from prometheus_client import Counter, Gauge, Histogram

BATCHES_PROCESSED_TOTAL = Counter(
    "warehouse_pg_consumer_batches_processed_total",
    "Total batches processed by the Postgres consumer",
    labelnames=["team_id", "schema_id", "status"],
)

BATCH_PROCESSING_DURATION_SECONDS = Histogram(
    "warehouse_pg_consumer_batch_processing_duration_seconds",
    "Duration of individual batch processing",
    labelnames=["team_id", "schema_id"],
    buckets=(0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0),
)

BATCH_RETRY_TOTAL = Counter(
    "warehouse_pg_consumer_batch_retry_total",
    "Total batch retry attempts",
    labelnames=["attempt", "error_type"],
)

RUNS_FAILED_TOTAL = Counter(
    "warehouse_pg_consumer_runs_failed_total",
    "Total runs fully failed via fail_run()",
)

POLL_DURATION_SECONDS = Histogram(
    "warehouse_pg_consumer_poll_duration_seconds",
    "Duration of Postgres poll queries",
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
)

POLL_BATCHES_FETCHED = Histogram(
    "warehouse_pg_consumer_poll_batches_fetched",
    "Number of batches returned per poll cycle",
    buckets=(0, 1, 5, 10, 25, 50, 100, 250, 500),
)

ACTIVE_GROUPS = Gauge(
    "warehouse_pg_consumer_active_groups",
    "Number of (team_id, schema_id) groups currently being processed",
    multiprocess_mode="livesum",
)

RECOVERY_SWEEPS_TOTAL = Counter(
    "warehouse_pg_consumer_recovery_sweeps_total",
    "Total recovery sweeps executed",
    labelnames=["outcome"],
)

RUNS_RECONCILED_TOTAL = Counter(
    "warehouse_pg_consumer_runs_reconciled_total",
    "Runs whose ExternalDataJob was left non-terminal despite a failed queue batch and "
    "was reconciled to Failed by the reconcile sweep",
)


@dataclass(frozen=True)
class ConsumerMetrics:
    """The metric set the shared batch-consumer engine emits.

    The Delta consumer keeps the historical un-prefixed ``warehouse_pg_consumer_*``
    names; other sinks get their own families via :func:`make_consumer_metrics` so
    dashboards, alerts, and KEDA queries never conflate two consumers' series.
    """

    batches_processed_total: Counter
    batch_processing_duration_seconds: Histogram
    batch_retry_total: Counter
    runs_failed_total: Counter
    poll_duration_seconds: Histogram
    poll_batches_fetched: Histogram
    active_groups: Gauge
    recovery_sweeps_total: Counter


DELTA_CONSUMER_METRICS = ConsumerMetrics(
    batches_processed_total=BATCHES_PROCESSED_TOTAL,
    batch_processing_duration_seconds=BATCH_PROCESSING_DURATION_SECONDS,
    batch_retry_total=BATCH_RETRY_TOTAL,
    runs_failed_total=RUNS_FAILED_TOTAL,
    poll_duration_seconds=POLL_DURATION_SECONDS,
    poll_batches_fetched=POLL_BATCHES_FETCHED,
    active_groups=ACTIVE_GROUPS,
    recovery_sweeps_total=RECOVERY_SWEEPS_TOTAL,
)

_metrics_by_prefix: dict[str, ConsumerMetrics] = {}


def make_consumer_metrics(prefix: str) -> ConsumerMetrics:
    """Build (once per process) the engine metric set under ``{prefix}_pg_consumer_*``."""
    existing = _metrics_by_prefix.get(prefix)
    if existing is not None:
        return existing

    p = f"{prefix}_pg_consumer"
    metrics = ConsumerMetrics(
        batches_processed_total=Counter(
            f"{p}_batches_processed_total",
            f"Total batches processed by the {prefix} Postgres consumer",
            labelnames=["team_id", "schema_id", "status"],
        ),
        batch_processing_duration_seconds=Histogram(
            f"{p}_batch_processing_duration_seconds",
            "Duration of individual batch processing",
            labelnames=["team_id", "schema_id"],
            buckets=(0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0, 600.0),
        ),
        batch_retry_total=Counter(
            f"{p}_batch_retry_total",
            "Total batch retry attempts",
            labelnames=["attempt", "error_type"],
        ),
        runs_failed_total=Counter(
            f"{p}_runs_failed_total",
            "Total runs fully failed via fail_run()",
        ),
        poll_duration_seconds=Histogram(
            f"{p}_poll_duration_seconds",
            "Duration of Postgres poll queries",
            buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0),
        ),
        poll_batches_fetched=Histogram(
            f"{p}_poll_batches_fetched",
            "Number of batches returned per poll cycle",
            buckets=(0, 1, 5, 10, 25, 50, 100, 250, 500),
        ),
        active_groups=Gauge(
            f"{p}_active_groups",
            "Number of (team_id, schema_id) groups currently being processed",
            multiprocess_mode="livesum",
        ),
        recovery_sweeps_total=Counter(
            f"{p}_recovery_sweeps_total",
            "Total recovery sweeps executed",
            labelnames=["outcome"],
        ),
    )
    _metrics_by_prefix[prefix] = metrics
    return metrics
