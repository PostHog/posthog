import pytest

from clickhouse_driver.errors import NetworkError, ServerException, SocketTimeoutError
from rest_framework.exceptions import APIException

from posthog.exceptions import (
    ClickHouseAtCapacity,
    ClickHouseClusterMemoryLimitExceeded,
    ClickHouseEstimatedQueryExecutionTimeTooLong,
    ClickHouseQueryMemoryLimitExceeded,
    ClickHouseQuerySizeExceeded,
    ClickHouseQueryTimeOut,
)

from products.posthog_ai.backend.mcp_tool_errors import MCPToolErrorDetails

from ee.hogai.tool_errors import MaxToolAccessDeniedError, MaxToolRetryableError, MaxToolTransientError


@pytest.mark.parametrize(
    "cause,error_type,code,retry_strategy",
    [
        (MaxToolRetryableError("Invalid query with private input"), "validation", "invalid_input", "adjusted"),
        (MaxToolTransientError("Temporarily unavailable"), "api_5xx", "service_unavailable", "once"),
        (MaxToolAccessDeniedError("insight", "viewer"), "permission", "permission_denied", "never"),
        (ClickHouseAtCapacity(), "rate_limited", "query_capacity_exceeded", "once"),
        (ClickHouseClusterMemoryLimitExceeded(), "rate_limited", "query_capacity_exceeded", "once"),
        (ClickHouseQueryTimeOut(), "timeout", "query_timeout", "adjusted"),
        (ClickHouseQueryMemoryLimitExceeded(), "api_5xx", "query_memory_limit_exceeded", "adjusted"),
        (ClickHouseEstimatedQueryExecutionTimeTooLong(), "api_5xx", "query_limit_exceeded", "adjusted"),
        (ClickHouseQuerySizeExceeded(), "api_5xx", "query_limit_exceeded", "adjusted"),
        (SocketTimeoutError("private host"), "timeout", "query_timeout", "once"),
        (NetworkError("private host"), "api_5xx", "service_unavailable", "once"),
        (APIException("Serialized query failure"), "api_5xx", "service_unavailable", "never"),
        (RuntimeError("private query text"), "internal", "internal_error", "never"),
    ],
)
@pytest.mark.parametrize("wrapper_link", [None, "__cause__", "__context__"], ids=["direct", "cause", "context"])
def test_error_classification(
    cause: Exception, error_type: str, code: str, retry_strategy: str, wrapper_link: str | None
) -> None:
    error = cause
    if wrapper_link:
        error = MaxToolRetryableError("private helper message")
        setattr(error, wrapper_link, cause)

    assert MCPToolErrorDetails.from_exception(error).model_dump() == {
        "type": error_type,
        "code": code,
        "retry_strategy": retry_strategy,
    }


def test_explicit_cause_takes_precedence_over_context() -> None:
    error = MaxToolRetryableError("private helper message")
    error.__context__ = MaxToolAccessDeniedError("insight", "viewer")
    error.__cause__ = NetworkError("private host")

    assert MCPToolErrorDetails.from_exception(error).model_dump() == {
        "type": "api_5xx",
        "code": "service_unavailable",
        "retry_strategy": "once",
    }


def test_suppressed_context_does_not_override_exposed_error() -> None:
    error = MaxToolRetryableError("private invalid input")
    error.__context__ = NetworkError("private host")
    error.__suppress_context__ = True

    assert MCPToolErrorDetails.from_exception(error).model_dump() == {
        "type": "validation",
        "code": "invalid_input",
        "retry_strategy": "adjusted",
    }


@pytest.mark.parametrize("link", ["__cause__", "__context__"])
def test_exception_cycles_do_not_enable_retry_for_unknown_failures(link: str) -> None:
    error = MaxToolRetryableError("private helper message")
    cause = RuntimeError("private unknown failure")
    setattr(error, link, cause)
    setattr(cause, link, error)

    assert MCPToolErrorDetails.from_exception(error).model_dump() == {
        "type": "internal",
        "code": "internal_error",
        "retry_strategy": "never",
    }


def test_original_error_takes_precedence_over_transient_wrapper() -> None:
    error = MaxToolTransientError("private helper message")
    error.__cause__ = MaxToolAccessDeniedError("insight", "viewer")

    assert MCPToolErrorDetails.from_exception(error).model_dump() == {
        "type": "permission",
        "code": "permission_denied",
        "retry_strategy": "never",
    }


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
