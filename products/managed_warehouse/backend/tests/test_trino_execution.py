import asyncio
import threading

import pytest
from unittest.mock import MagicMock, patch

from structlog.testing import capture_logs
from trino.exceptions import HttpError, TrinoQueryError, TrinoUserError

from products.managed_warehouse.backend import trino_execution as execution

INSTANCE_REPLACED_MESSAGE = (
    "Query killed by user 'ops'. Message: this query was cancelled because the Trino instance "
    "running it was being replaced; please run it again"
)


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
async def test_logs_each_query_id_while_the_model_is_still_running() -> None:
    first_query_id = "20261118_000000_00001_first"
    second_query_id = "20261118_000000_00002_second"
    cursor = MagicMock(query_id=first_query_id)
    release = threading.Event()

    def execute(control: execution.TrinoQueryControl) -> int:
        control.attach(cursor)
        assert release.wait(10)
        return 42

    def logged_query_ids() -> list[str]:
        return [log["trino_query_id"] for log in logs if "trino_query_id" in log]

    async def until_logged(count: int) -> None:
        async with asyncio.timeout(10):
            while len(logged_query_ids()) < count:
                await asyncio.sleep(0)

    with patch.object(execution, "TRINO_QUERY_ID_LOG_SECONDS", 0), capture_logs() as logs:
        task = asyncio.create_task(execution.run_trino_model(execute, query_seconds=60))
        try:
            await until_logged(1)
            for _ in range(3):
                await asyncio.sleep(0)
            cursor.query_id = second_query_id
            await until_logged(2)
        finally:
            release.set()
        assert await task == 42

    assert logged_query_ids() == [first_query_id, second_query_id]


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
        (TrinoUserError({"errorName": "ADMINISTRATIVELY_KILLED", "message": INSTANCE_REPLACED_MESSAGE}), 2),
        (
            TrinoUserError(
                {
                    "errorName": "ADMINISTRATIVELY_KILLED",
                    "message": "Query killed by user 'ops'. Message: runaway query",
                }
            ),
            1,
        ),
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "retry_delays,query_seconds,expected_attempts,expected_message",
    [
        (
            (0, 0),
            60,
            3,
            "Trino restarted while it was building this model, and all 3 attempts failed. "
            "The model's query did not cause this. The model builds again on its next scheduled run, "
            "or you can run it now. Trino query ID: 20261119_000000_00003_abcde",
        ),
        (
            (3600,),
            60,
            1,
            "Trino restarted while it was building this model, and there was not enough time left to try again. "
            "The model's query did not cause this. The model builds again on its next scheduled run, "
            "or you can run it now. Trino query ID: 20261119_000000_00001_abcde",
        ),
    ],
)
async def test_reports_a_trino_restart_once_the_retries_run_out(
    retry_delays: tuple[float, ...], query_seconds: float, expected_attempts: int, expected_message: str
) -> None:
    attempts = 0

    def execute(control: execution.TrinoQueryControl) -> int:
        nonlocal attempts
        attempts += 1
        raise TrinoUserError(
            {"errorName": "ADMINISTRATIVELY_KILLED", "errorType": "USER_ERROR", "message": INSTANCE_REPLACED_MESSAGE},
            f"20261119_000000_0000{attempts}_abcde",
        )

    with pytest.raises(execution.TrinoInstanceReplacedError) as raised:
        await execution.run_trino_model_with_retries(execute, query_seconds=query_seconds, retry_delays=retry_delays)

    assert attempts == expected_attempts
    assert str(raised.value) == expected_message
