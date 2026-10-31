import asyncio
import threading

import pytest
from unittest.mock import MagicMock, patch

from trino.exceptions import HttpError, TrinoQueryError, TrinoUserError

from products.managed_warehouse.backend import trino_execution as execution


@pytest.mark.asyncio
@pytest.mark.parametrize("deadline_expired", [False, True])
async def test_cancellation_reaches_cursor_and_waits_for_cleanup(deadline_expired: bool) -> None:
    loop = asyncio.get_running_loop()
    entered = asyncio.Event()
    canceled = asyncio.Event()
    stopped = threading.Event()
    cleanup = threading.Event()
    cursor = MagicMock()
    timeout = asyncio.timeout(None)

    def cancel() -> None:
        stopped.set()
        loop.call_soon_threadsafe(canceled.set)

    cursor.cancel.side_effect = cancel

    def execute(control: execution.TrinoQueryControl) -> int:
        control.attach(cursor)
        loop.call_soon_threadsafe(entered.set)
        assert stopped.wait(10)
        assert cleanup.wait(10)
        return 1

    with patch.object(execution.asyncio, "timeout", return_value=timeout):
        task = asyncio.create_task(execution.run_trino_model(execute, query_seconds=60))
        try:
            await asyncio.wait_for(entered.wait(), timeout=10)
            if deadline_expired:
                timeout.reschedule(loop.time())
            else:
                task.cancel()
            await asyncio.wait_for(canceled.wait(), timeout=10)
            assert not task.done()
            cleanup.set()
            with pytest.raises(
                TimeoutError if deadline_expired else asyncio.CancelledError,
                match="Trino model execution exceeded its 1-minute deadline" if deadline_expired else None,
            ):
                await task
            cursor.cancel.assert_called()
        finally:
            stopped.set()
            cleanup.set()
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_success_preserves_result() -> None:
    assert await execution.run_trino_model(lambda control: 42, query_seconds=60) == 42


@pytest.mark.asyncio
async def test_reports_cpu_time() -> None:
    cpu_milliseconds: list[int] = []

    def execute(control: execution.TrinoQueryControl) -> int:
        control.record_cpu_milliseconds(25)
        return 42

    assert await execution.run_trino_model(execute, query_seconds=60, on_cpu_milliseconds=cpu_milliseconds.append) == 42
    assert cpu_milliseconds == [25]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error,expected_attempts",
    [
        (TrinoQueryError({"errorName": "CLUSTER_OUT_OF_MEMORY", "message": "Query killed"}), 2),
        (TrinoQueryError({"errorName": "TOO_MANY_REQUESTS_FAILED", "message": "Query killed"}), 2),
        (TrinoQueryError({"errorName": "PAGE_TRANSPORT_TIMEOUT", "message": "Query killed"}), 2),
        (HttpError("error 403: b'This tenant is not admitted to the pool yet; the request was not dispatched'"), 2),
        (HttpError("error 403: b'Forbidden'"), 1),
        (
            TrinoUserError(
                {
                    "errorName": "COLUMN_NOT_FOUND",
                    "message": "line 1:8: Column 'This tenant is not admitted to the pool yet' cannot be resolved",
                }
            ),
            1,
        ),
        (TrinoQueryError({"errorName": "EXCEEDED_LOCAL_MEMORY_LIMIT", "message": "Query killed"}), 1),
    ],
)
async def test_retries_only_transient_trino_errors(error: Exception, expected_attempts: int) -> None:
    attempts = 0
    processed: list[int] = []

    def execute(control: execution.TrinoQueryControl) -> int:
        nonlocal attempts
        attempts += 1
        control.record_processed_bytes(10)
        if attempts == 1:
            raise error
        return 42

    if expected_attempts == 1:
        with pytest.raises(type(error)):
            await execution.run_trino_model_with_retries(
                execute, query_seconds=60, retry_delays=(0,), on_processed_bytes=processed.append
            )
    else:
        assert (
            await execution.run_trino_model_with_retries(
                execute, query_seconds=60, retry_delays=(0,), on_processed_bytes=processed.append
            )
            == 42
        )
    assert attempts == expected_attempts
    assert processed == [10] * expected_attempts


@pytest.mark.asyncio
async def test_deadline_after_a_retry_reports_the_whole_budget() -> None:
    attempts = 0

    def execute(control: execution.TrinoQueryControl) -> int:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise TrinoQueryError({"errorName": "CLUSTER_OUT_OF_MEMORY", "message": "Query killed"})
        assert control.cancelled.wait(10)
        return 42

    with pytest.raises(TimeoutError, match=r"exceeded its 0\.01-minute deadline after 2 attempts"):
        await execution.run_trino_model_with_retries(execute, query_seconds=0.6, retry_delays=(0,))
