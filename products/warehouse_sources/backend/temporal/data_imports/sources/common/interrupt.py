from temporalio import activity

from posthog.temporal.common.shutdown import WorkerShuttingDownError

from products.warehouse_sources.backend.temporal.data_imports.util import NonRetryableException


def raise_if_interrupted() -> None:
    """Cooperatively abort a blocking source between network calls.

    Long synchronous source work — paginated HTTP fetches and per-page association
    backfills — runs in a worker thread where neither Temporal's activity cancellation
    nor a worker shutdown can interrupt an in-flight ``requests`` call. Calling this
    between calls lets the source unwind promptly instead of grinding on for tens of
    thousands more rows after a cancel or through a redeploy.

    - Worker shutdown -> ``WorkerShuttingDownError`` (retryable; a fresh worker resumes).
    - Activity cancellation -> ``NonRetryableException`` (this run is stopping for good).

    A no-op outside an activity context, so sources stay unit-testable.
    """
    if not activity.in_activity():
        return
    if activity.is_worker_shutdown():
        raise WorkerShuttingDownError.from_activity_context()
    if activity.is_cancelled():
        raise NonRetryableException("Sync was cancelled")
