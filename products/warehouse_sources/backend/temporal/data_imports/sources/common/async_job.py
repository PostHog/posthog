"""Polling for a vendor job that runs asynchronously: a report, an export or a search job.

Many vendors use the same flow. The source creates a job, polls its status until it is done, and
then downloads the result. `poll_until_done` is the poll step. Each wait goes through
`interruptible_wait`, so a worker that starts to shut down does not stay in the wait.
"""

import time
from collections.abc import Callable
from typing import cast

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.interruptible_wait import (
    interruptible_wait,
)


@frozen
class JobStatus[T]:
    """One status check of a job. A status that is not done and not failed means the job is pending."""

    done: bool = False
    failed: bool = False
    # The value that `poll_until_done` returns when the job is done, for example a download URL.
    result: T | None = None
    # The status that the vendor reported. The default errors show it to the user.
    message: str = ""

    def __post_init__(self) -> None:
        if self.done and self.failed:
            raise ValueError("A job status cannot be done and failed at the same time")


class AsyncJobFailedError(Exception):
    pass


class AsyncJobTimeoutError(Exception):
    pass


def poll_until_done[T](
    check: Callable[[], JobStatus[T]],
    *,
    interval: float,
    budget_seconds: float,
    safe_point: Callable[[], None] | None = None,
    wait_first: bool = False,
    failed_error: Callable[[JobStatus[T]], Exception] | None = None,
    timeout_error: Callable[[JobStatus[T]], Exception] | None = None,
) -> T:
    """Call `check` until the job is done, and return the `result` of the last status.

    Raise `failed_error(status)` when the job fails. Raise `timeout_error(status)` when the waits
    reach `budget_seconds` and the job is still pending. Without these factories, the errors are
    `AsyncJobFailedError` and `AsyncJobTimeoutError`.

    The budget counts the time of each status check, and `interval` seconds for each wait, also
    when the wait ends early. Thus slow status checks cannot extend the poll, and a shutdown
    cannot make the poll call the vendor without a limit.

    Pass `safe_point` only when the run can stop and resume at the poll without losing rows. The
    poll then reaches it before each wait, and a shutdown during a wait hands the run to another
    worker. Without it, a shutdown only makes the waits shorter.

    Set `wait_first` when the vendor rejects a status check right after it creates the job.
    """
    waited = 0.0
    if wait_first:
        _wait(interval, safe_point)
        waited += interval
    while True:
        check_started = time.monotonic()
        status = check()
        waited += time.monotonic() - check_started
        if status.done:
            return cast(T, status.result)
        if status.failed:
            if failed_error is not None:
                raise failed_error(status)
            raise AsyncJobFailedError(f"The job failed: {status.message}" if status.message else "The job failed")
        if waited >= budget_seconds:
            if timeout_error is not None:
                raise timeout_error(status)
            raise AsyncJobTimeoutError(f"The job is still {status.message or 'pending'} after {waited:.0f} seconds")
        _wait(interval, safe_point)
        waited += interval


def _wait(seconds: float, safe_point: Callable[[], None] | None) -> None:
    if safe_point is not None:
        safe_point()
    interruptible_wait(seconds, safe_point=safe_point)
