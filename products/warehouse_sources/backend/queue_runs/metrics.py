"""Prometheus metrics for queue runs.

The extraction body records OTel metrics only inside a Temporal activity, so a queue run records
these instead.
"""

from __future__ import annotations

import enum

from prometheus_client import Counter, Histogram


class RunOutcome(enum.StrEnum):
    # The run produced no batch, so the handler completed the job itself.
    COMPLETED = "completed"
    # The run produced batches, and the loader finishes the job.
    HANDED_TO_LOADER = "handed_to_loader"
    BILLING_LIMIT_REACHED = "billing_limit_reached"
    FAILED = "failed"
    RETRY = "retry"
    SHUTDOWN_RETRY = "shutdown_retry"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class SkipReason(enum.StrEnum):
    OVERLAP = "overlap"
    REPARTITION_HOLD = "repartition_hold"
    ALREADY_TERMINAL = "already_terminal"
    DISABLED = "disabled"


RUNS_FINISHED_TOTAL = Counter(
    "warehouse_extract_runs_finished_total",
    "Extract-lane handler calls, by how the call ended.",
    labelnames=["source_type", "outcome"],
)

RUN_DURATION_SECONDS = Histogram(
    "warehouse_extract_run_duration_seconds",
    "Wall-clock time of one extract-lane handler call, by how the call ended.",
    labelnames=["outcome"],
    buckets=(1, 5, 15, 30, 60, 300, 900, 1800, 3600, 3 * 3600, 6 * 3600, 12 * 3600, 24 * 3600, 6 * 24 * 3600),
)

ROWS_EXTRACTED_TOTAL = Counter(
    "warehouse_extract_rows_extracted_total",
    "Rows that queue runs staged for the loader.",
    labelnames=["source_type"],
)

RUNS_SKIPPED_TOTAL = Counter(
    "warehouse_extract_runs_skipped_total",
    "Queue runs that ended without extracting, by reason.",
    labelnames=["reason"],
)
