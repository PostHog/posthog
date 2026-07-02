import pytest
from unittest.mock import MagicMock, patch

from clickhouse_driver.errors import SocketTimeoutError

from posthog.exceptions import ClickHouseAtCapacity

from products.signals.backend.temporal.clickhouse import execute_hogql_query_with_retry

MODULE_PATH = "products.signals.backend.temporal.clickhouse"


@pytest.mark.parametrize(
    "transient_error",
    [
        # SocketTimeoutError is raised at connection-establishment time and is not part of
        # CH_TRANSIENT_ERRORS, so it must be explicitly retriable.
        SocketTimeoutError(),
        ClickHouseAtCapacity(),
    ],
)
async def test_retries_transient_error_then_succeeds(transient_error: Exception) -> None:
    sentinel = object()
    with patch(f"{MODULE_PATH}.execute_hogql_query", side_effect=[transient_error, sentinel]) as mock_execute:
        result = await execute_hogql_query_with_retry(
            query_type="test",
            query="SELECT 1",
            team=MagicMock(),
            base_delay=0,  # keep the backoff sleep instant and deterministic
        )

    assert result is sentinel
    assert mock_execute.call_count == 2


async def test_non_retriable_error_propagates_without_retry() -> None:
    with patch(f"{MODULE_PATH}.execute_hogql_query", side_effect=ValueError("boom")) as mock_execute:
        with pytest.raises(ValueError):
            await execute_hogql_query_with_retry(
                query_type="test",
                query="SELECT 1",
                team=MagicMock(),
                base_delay=0,
            )

    assert mock_execute.call_count == 1
