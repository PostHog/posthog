import time
import asyncio
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

import psycopg
from prometheus_client import Counter, Gauge, Histogram

# The claim query degrades with queue backlog, and its danger zone sits near the
# 300s group-lease TTL (a poll slower than TTL/2 hands groups over mostly
# expired). The old 5s ceiling made every degraded poll indistinguishable from a
# merely slow one — p95 sat "pinned at 5s" while real polls took minutes.
POLL_DURATION_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 15.0, 60.0, 150.0, 300.0)

# Deliberately not labeled by team/schema: every (team, schema) combo mints
# series forever (12 per combo on the histogram), and no dashboard or alert
# reads them. Per-team debugging belongs in the structured logs.
BATCHES_PROCESSED_TOTAL = Counter(
    "warehouse_pg_consumer_batches_processed_total",
    "Total batches processed by the Postgres consumer",
    labelnames=["status"],
)

BATCH_PROCESSING_DURATION_SECONDS = Histogram(
    "warehouse_pg_consumer_batch_processing_duration_seconds",
    "Duration of individual batch processing",
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
    buckets=POLL_DURATION_BUCKETS,
)

# Failed polls never reach the histograms above, so a fleet whose polls all
# time out looks better on those — this counter is the alertable signal.
POLL_FAILURES_TOTAL = Counter(
    "warehouse_pg_consumer_poll_failures_total",
    "Poll cycles that failed before returning batches",
    labelnames=["reason"],
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

RUNS_TERMINALIZED_STALE_TOTAL = Counter(
    "warehouse_pg_consumer_runs_terminalized_stale_total",
    "Runs the loader abandoned (non-terminal batches, no live lease, no progress past the "
    "staleness threshold) that the reconcile sweep failed before the retention prune would",
)

# The loader's data-freshness signal: it rises whenever loading stalls,
# regardless of why (wedged consumers, claim-query degradation, crashloops).
# Every pod reports the same queue-wide value, so aggregate with max().
# livemax matches that: it stays accurate even if two consumer processes
# briefly co-exist in one pod, where livesum would double the age.
OLDEST_UNCLAIMED_BATCH_SECONDS = Gauge(
    "warehouse_pg_queue_oldest_unclaimed_batch_seconds",
    "Age of the oldest queue batch no consumer has picked up yet (0 = none waiting). "
    "Sampled on the reconcile cadence; saturates at the freshness probe window.",
    multiprocess_mode="livemax",
)

# Depth companion to the age gauge above: age says how stale the head of the queue
# is, depth says how much work is behind it — a stall and a burst look identical on
# age alone. Same probe, same cadence, same aggregation (max across pods).
CLAIMABLE_BATCHES = Gauge(
    "warehouse_pg_queue_claimable_batches",
    "Batches whose state makes them claimable right now (pending or waiting_retry, "
    "within the claim eligibility window; per-run and lease gates not applied). "
    "Sampled on the reconcile cadence.",
    multiprocess_mode="livemax",
)

# The maintenance queries (sweeps, reconcile passes, probes) shaped like the claim
# poll: cost scales with queue state, and the 2026-08 stall came from one that had
# no latency signal at all. Same bucket ceiling rationale as POLL_DURATION_BUCKETS.
QUEUE_QUERY_DURATION_SECONDS = Histogram(
    "warehouse_pg_queue_query_duration_seconds",
    "Duration of maintenance queries against the batch queue, by query name. "
    "Observed on success AND on failure/timeout, so degradation is never invisible.",
    labelnames=["query"],
    buckets=POLL_DURATION_BUCKETS,
)

QUEUE_QUERY_FAILURES_TOTAL = Counter(
    "warehouse_pg_queue_query_failures_total",
    "Maintenance queue queries that raised or timed out before returning. "
    "Probe timeouts count as reason=cancelled, not timeout: asyncio.timeout "
    "cancels the timed block and only converts to TimeoutError outside it. "
    "Worker-shutdown cancellations mid-query land under cancelled too, so "
    "expect a small rate during deploys.",
    labelnames=["query", "reason"],
)


def _failure_reason(exc: BaseException) -> str:
    """Small, fixed label set: exception class names (psycopg has hundreds) would bloat cardinality."""
    # Fires only for a TimeoutError raised inside the timed block, which psycopg
    # never does (its timeouts are psycopg.Error subclasses, so reason=db).
    # Kept as defensive coverage; alert on cancelled, not this.
    if isinstance(exc, TimeoutError):
        return "timeout"
    # asyncio.timeout cancels the timed block; the CancelledError is what this code
    # sees. Worker-shutdown cancellation is indistinguishable and lands here too.
    if isinstance(exc, asyncio.CancelledError):
        return "cancelled"
    if isinstance(exc, psycopg.Error):
        return "db"
    return "other"


@contextmanager
def observe_queue_query(query: str) -> Iterator[None]:
    """Time a maintenance queue query; failures still record their elapsed time.

    The duration is observed in ``finally``, deliberately including the failure
    and timeout paths: the poll histogram's original design only recorded
    successes, so a fleet whose queries all timed out looked *faster* on the
    histogram exactly when it was slowest, and only a separate counter told the
    truth. Here the histogram carries the whole story and the failure counter
    adds the why.
    """
    start = time.monotonic()
    try:
        yield
    except BaseException as e:
        QUEUE_QUERY_FAILURES_TOTAL.labels(query=query, reason=_failure_reason(e)).inc()
        raise
    finally:
        QUEUE_QUERY_DURATION_SECONDS.labels(query=query).observe(time.monotonic() - start)


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
    poll_failures_total: Counter
    active_groups: Gauge
    recovery_sweeps_total: Counter


DELTA_CONSUMER_METRICS = ConsumerMetrics(
    batches_processed_total=BATCHES_PROCESSED_TOTAL,
    batch_processing_duration_seconds=BATCH_PROCESSING_DURATION_SECONDS,
    batch_retry_total=BATCH_RETRY_TOTAL,
    runs_failed_total=RUNS_FAILED_TOTAL,
    poll_duration_seconds=POLL_DURATION_SECONDS,
    poll_batches_fetched=POLL_BATCHES_FETCHED,
    poll_failures_total=POLL_FAILURES_TOTAL,
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
            labelnames=["status"],
        ),
        batch_processing_duration_seconds=Histogram(
            f"{p}_batch_processing_duration_seconds",
            "Duration of individual batch processing",
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
            buckets=POLL_DURATION_BUCKETS,
        ),
        poll_batches_fetched=Histogram(
            f"{p}_poll_batches_fetched",
            "Number of batches returned per poll cycle",
            buckets=(0, 1, 5, 10, 25, 50, 100, 250, 500),
        ),
        poll_failures_total=Counter(
            f"{p}_poll_failures_total",
            "Poll cycles that failed before returning batches",
            labelnames=["reason"],
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
