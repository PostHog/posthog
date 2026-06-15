import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from django.db import OperationalError

from products.signals.backend.temporal.clickhouse import RETRIABLE_ERRORS, execute_hogql_query_with_retry

MODULE = "products.signals.backend.temporal.clickhouse"


def test_django_operational_error_is_retriable():
    assert OperationalError in RETRIABLE_ERRORS


async def test_retries_on_stale_connection_then_succeeds():
    sentinel = object()
    inner = AsyncMock(side_effect=[OperationalError("the connection is closed"), sentinel])
    with (
        patch(f"{MODULE}.database_sync_to_async_pool", return_value=inner) as pool,
        patch(f"{MODULE}._sleep_with_heartbeat", new=AsyncMock()) as sleep,
    ):
        result = await execute_hogql_query_with_retry(
            query_type="SignalsFetchForReport",
            query="select 1",
            team=MagicMock(),
            max_retries=2,
            base_delay=0.0,
        )

    assert result is sentinel
    assert inner.await_count == 2
    # The query callable is re-wrapped each attempt so close_old_connections runs in the executor thread.
    assert pool.call_count == 2
    sleep.assert_awaited_once()


async def test_raises_after_exhausting_retries_on_operational_error():
    inner = AsyncMock(side_effect=OperationalError("the connection is closed"))
    with (
        patch(f"{MODULE}.database_sync_to_async_pool", return_value=inner),
        patch(f"{MODULE}._sleep_with_heartbeat", new=AsyncMock()),
    ):
        with pytest.raises(OperationalError):
            await execute_hogql_query_with_retry(
                query_type="SignalsFetchForReport",
                query="select 1",
                team=MagicMock(),
                max_retries=1,
                base_delay=0.0,
            )

    assert inner.await_count == 2  # initial attempt + one retry


async def test_non_retriable_error_propagates_without_retry():
    inner = AsyncMock(side_effect=ValueError("boom"))
    with (
        patch(f"{MODULE}.database_sync_to_async_pool", return_value=inner),
        patch(f"{MODULE}._sleep_with_heartbeat", new=AsyncMock()) as sleep,
    ):
        with pytest.raises(ValueError):
            await execute_hogql_query_with_retry(
                query_type="SignalsFetchForReport",
                query="select 1",
                team=MagicMock(),
                max_retries=3,
                base_delay=0.0,
            )

    assert inner.await_count == 1
    sleep.assert_not_awaited()
