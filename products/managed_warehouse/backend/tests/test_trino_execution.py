import asyncio
import threading

import pytest
from unittest.mock import MagicMock, patch

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
        task = asyncio.create_task(execution.run_trino_model(execute))
        try:
            await asyncio.wait_for(entered.wait(), timeout=10)
            if deadline_expired:
                timeout.reschedule(loop.time())
            else:
                task.cancel()
            await asyncio.wait_for(canceled.wait(), timeout=10)
            assert not task.done()
            cleanup.set()
            with pytest.raises(TimeoutError if deadline_expired else asyncio.CancelledError):
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
    assert await execution.run_trino_model(lambda control: 42) == 42
