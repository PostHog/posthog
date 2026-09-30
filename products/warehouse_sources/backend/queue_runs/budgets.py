"""Attempt caps and wall-clock budgets for queue runs.

The caps mirror the retry policy `ExternalDataJobWorkflow` gives its import activity, per run
shape. The wall-clock budgets are shorter than Temporal's one week for long runs, because a queue
job stops being claimable 6.5 days after it is enqueued and its partition drops at 7 days.
"""

from __future__ import annotations

import enum
from datetime import datetime, timedelta

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports import external_data_job
from products.warehouse_sources.backend.temporal.data_imports.retry_limits import (
    MAX_RESUMABLE_SOURCE_RETRIES_PRODUCTION,
)
from products.warehouse_sources.backend.temporal.data_imports.sources import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import ResumableSource
from products.warehouse_sources.backend.types import ExternalDataSourceType
from products.warehouse_sources_queue.backend.sdk import JOB_CLAIM_ELIGIBILITY

FULL_REFRESH_MAX_ATTEMPTS = 3
FULL_REFRESH_TIMEOUT = timedelta(hours=24)
LONG_RUN_TIMEOUT = timedelta(days=6)

# Shutdown requeues do not count against a run's cap, but the engine counts every attempt. The
# engine's cap is this much above the largest run cap, so a few deploys do not fail a run.
SHUTDOWN_REQUEUE_ALLOWANCE = 10
CONSUMER_MAX_ATTEMPTS = MAX_RESUMABLE_SOURCE_RETRIES_PRODUCTION + SHUTDOWN_REQUEUE_ALLOWANCE

# A retry must be claimed and must run before the claim window closes. Closer than this to the end
# of the window, the handler fails the run instead of retrying it.
RETRY_WINDOW_MARGIN = timedelta(hours=1)


class RunShape(enum.StrEnum):
    RESUMABLE = "resumable"
    INCREMENTAL = "incremental"
    FULL_REFRESH = "full_refresh"


@frozen
class RunBudget:
    shape: RunShape
    # Attempts that count, the first attempt included. Shutdown requeues do not count.
    max_attempts: int
    timeout: timedelta


def run_budget(*, source_type: str, incremental_or_append: bool, keyset_full_load_enabled: bool) -> RunBudget:
    """The budget the workflow would give this run, with the long timeout cut to fit the queue."""
    source = SourceRegistry.get_source(ExternalDataSourceType(source_type))
    # Same test as the workflow: the class can resume, and its resume covers a run of this shape.
    if isinstance(source, ResumableSource) and source.resume_covers_run(
        incremental_or_append=incremental_or_append,
        keyset_full_load_enabled=keyset_full_load_enabled,
    ):
        return RunBudget(
            shape=RunShape.RESUMABLE,
            max_attempts=external_data_job.MAX_RESUMABLE_SOURCE_RETRIES,
            timeout=LONG_RUN_TIMEOUT,
        )
    if incremental_or_append:
        return RunBudget(
            shape=RunShape.INCREMENTAL,
            max_attempts=external_data_job.MAX_INCREMENTAL_SOURCE_RETRIES,
            timeout=LONG_RUN_TIMEOUT,
        )
    return RunBudget(shape=RunShape.FULL_REFRESH, max_attempts=FULL_REFRESH_MAX_ATTEMPTS, timeout=FULL_REFRESH_TIMEOUT)


def claim_deadline(job_created_at: datetime) -> datetime:
    """When the queue job stops being claimable. A run must end before this time."""
    return job_created_at + JOB_CLAIM_ELIGIBILITY
