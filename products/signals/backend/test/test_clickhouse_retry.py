from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from posthog.errors import CHQueryErrorTooManySimultaneousQueries
from posthog.exceptions import ClickHouseAtCapacity, ClickHouseQueryTimeOut

from products.signals.backend.temporal.clickhouse import execute_hogql_query_with_retry

CLICKHOUSE_MODULE = "products.signals.backend.temporal.clickhouse"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        # A transiently slow query surfaces as ClickHouseQueryTimeOut; the signals pipeline queries
        # are bounded, so a timeout should get a backed-off retry rather than failing the activity.
        ClickHouseQueryTimeOut(),
        ClickHouseAtCapacity(),
        CHQueryErrorTooManySimultaneousQueries("busy"),
    ],
)
async def test_retries_then_succeeds_on_transient_error(error: Exception) -> None:
    call = MagicMock(side_effect=[error, "ok"])

    with patch(f"{CLICKHOUSE_MODULE}.execute_hogql_query", call):
        result = await execute_hogql_query_with_retry(
            query_type="T",
            query="SELECT 1",
            team=MagicMock(),
            base_delay=0,
        )

    assert result == "ok"
    assert call.call_count == 2


@pytest.mark.asyncio
async def test_does_not_retry_unexpected_error() -> None:
    call = MagicMock(side_effect=ValueError("boom"))

    with patch(f"{CLICKHOUSE_MODULE}.execute_hogql_query", call):
        with pytest.raises(ValueError):
            await execute_hogql_query_with_retry(
                query_type="T",
                query="SELECT 1",
                team=MagicMock(),
                base_delay=0,
            )

    assert call.call_count == 1
