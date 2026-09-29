import pytest

from clickhouse_driver.errors import ServerException
from rest_framework.exceptions import APIException

from posthog.exceptions import ClickHouseEstimatedQueryExecutionTimeTooLong, ClickHouseQuerySizeExceeded

from products.posthog_ai.backend.mcp_tool_errors import MCPToolErrorDetails

from ee.hogai.tool_errors import MaxToolRetryableError


@pytest.mark.parametrize(
    "error_class,server_code,server_message",
    [
        (ClickHouseEstimatedQueryExecutionTimeTooLong, 160, "Estimated query execution time is too long"),
        (ClickHouseQuerySizeExceeded, 62, "Syntax error: query size exceeded"),
    ],
)
@pytest.mark.parametrize("with_server_cause", [True, False], ids=["live_query", "replayed_failure"])
def test_query_limits_preserve_adjusted_recovery(
    error_class: type[APIException], server_code: int, server_message: str, with_server_cause: bool
) -> None:
    error = error_class()
    if with_server_cause:
        error.__cause__ = ServerException(server_message, code=server_code)

    try:
        raise error
    except Exception as cause:
        wrapped = MaxToolRetryableError(f"Error executing query: {cause}")
        wrapped.__cause__ = cause

    details = MCPToolErrorDetails.from_exception(wrapped)

    assert details.model_dump() == {
        "type": "api_5xx",
        "code": "query_limit_exceeded",
        "retry_strategy": "adjusted",
    }
    assert "narrower" in details.safe_message
