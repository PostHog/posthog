from enum import StrEnum
from typing import Literal

from django.db import OperationalError

from clickhouse_driver.errors import NetworkError, SocketTimeoutError
from pydantic import BaseModel, Field
from rest_framework.exceptions import APIException, PermissionDenied

from posthog.hogql.errors import TableAccessDeniedError

from posthog.api.statement_timeout import is_query_canceled
from posthog.errors import QueryErrorCategory, classify_query_error, wrap_clickhouse_query_error
from posthog.exceptions import (
    ClickHouseEstimatedQueryExecutionTimeTooLong,
    ClickHouseQueryMemoryLimitExceeded,
    ClickHouseQuerySizeExceeded,
    ClickHouseQueryTimeOut,
)

from products.access_control.backend.facade.user_access_control import UserAccessControlError

from ee.hogai.chat_agent.schema_generator.parsers import PydanticOutputParserException
from ee.hogai.tool_errors import MaxToolAccessDeniedError, MaxToolRetryableError, MaxToolTransientError


class MCPToolErrorCode(StrEnum):
    INVALID_INPUT = "invalid_input"
    PERMISSION_DENIED = "permission_denied"
    QUERY_TIMEOUT = "query_timeout"
    QUERY_CAPACITY_EXCEEDED = "query_capacity_exceeded"
    QUERY_MEMORY_LIMIT_EXCEEDED = "query_memory_limit_exceeded"
    QUERY_LIMIT_EXCEEDED = "query_limit_exceeded"
    SERVICE_UNAVAILABLE = "service_unavailable"
    INTERNAL_ERROR = "internal_error"


class MCPToolErrorDetails(BaseModel):
    type: Literal["validation", "permission", "timeout", "rate_limited", "api_5xx", "internal"] = Field(
        description="Value-free failure category for MCP analytics."
    )
    code: MCPToolErrorCode = Field(description="Stable failure code that contains no caller input.")
    retry_strategy: Literal["never", "once", "adjusted"] = Field(
        description="Whether the agent can retry unchanged once, retry with adjusted inputs, or should not retry."
    )

    @property
    def retry_hint(self) -> str:
        return {
            "never": " Do not automatically retry this tool call.",
            "once": " You may retry this operation once without changes.",
            "adjusted": " You may retry with adjusted inputs.",
        }[self.retry_strategy]

    @classmethod
    def from_exception(cls, error: Exception) -> "MCPToolErrorDetails":
        chain = _exception_chain(error)
        # Query helpers wrap typed failures to add agent-facing context. Classify the
        # original cause first so a service failure cannot become an input error.
        for cause in reversed(chain):
            details = cls._classify_exception(cause)
            if details is not None:
                return details
            if isinstance(cause, MaxToolRetryableError) and cause is chain[-1]:
                return cls(type="validation", code=MCPToolErrorCode.INVALID_INPUT, retry_strategy="adjusted")

        return cls(type="internal", code=MCPToolErrorCode.INTERNAL_ERROR, retry_strategy="never")

    @classmethod
    def _classify_query_error(cls, cause: Exception) -> "MCPToolErrorDetails | None":
        if isinstance(cause, (ClickHouseEstimatedQueryExecutionTimeTooLong, ClickHouseQuerySizeExceeded)):
            return cls(type="api_5xx", code=MCPToolErrorCode.QUERY_LIMIT_EXCEEDED, retry_strategy="adjusted")
        category = classify_query_error(cause)
        if category == QueryErrorCategory.RATE_LIMITED:
            return cls(type="rate_limited", code=MCPToolErrorCode.QUERY_CAPACITY_EXCEEDED, retry_strategy="once")
        if isinstance(cause, ClickHouseQueryMemoryLimitExceeded):
            return cls(type="api_5xx", code=MCPToolErrorCode.QUERY_MEMORY_LIMIT_EXCEEDED, retry_strategy="adjusted")
        if category == QueryErrorCategory.USER_ERROR or isinstance(cause, PydanticOutputParserException):
            return cls(type="validation", code=MCPToolErrorCode.INVALID_INPUT, retry_strategy="adjusted")
        return None

    @classmethod
    def _classify_api_error(cls, cause: APIException) -> "MCPToolErrorDetails":
        if cause.status_code == 429:
            return cls(type="rate_limited", code=MCPToolErrorCode.QUERY_CAPACITY_EXCEEDED, retry_strategy="once")
        if 400 <= cause.status_code < 500:
            return cls(type="validation", code=MCPToolErrorCode.INVALID_INPUT, retry_strategy="adjusted")
        return cls(type="api_5xx", code=MCPToolErrorCode.SERVICE_UNAVAILABLE, retry_strategy="never")

    @classmethod
    def _classify_exception(cls, cause: Exception) -> "MCPToolErrorDetails | None":
        # Raw ClickHouse errors and their typed wrappers must give the same
        # recovery advice, including per-query limits versus cluster pressure.
        cause = wrap_clickhouse_query_error(cause)
        if isinstance(
            cause, (MaxToolAccessDeniedError, UserAccessControlError, TableAccessDeniedError, PermissionDenied)
        ):
            return cls(type="permission", code=MCPToolErrorCode.PERMISSION_DENIED, retry_strategy="never")
        if isinstance(cause, ClickHouseQueryTimeOut):
            return cls(type="timeout", code=MCPToolErrorCode.QUERY_TIMEOUT, retry_strategy="adjusted")
        if isinstance(cause, (TimeoutError, SocketTimeoutError)) or (
            isinstance(cause, OperationalError) and is_query_canceled(cause)
        ):
            return cls(type="timeout", code=MCPToolErrorCode.QUERY_TIMEOUT, retry_strategy="once")
        details = cls._classify_query_error(cause)
        if details is not None:
            return details
        if isinstance(cause, (MaxToolTransientError, NetworkError)):
            return cls(type="api_5xx", code=MCPToolErrorCode.SERVICE_UNAVAILABLE, retry_strategy="once")
        if isinstance(cause, APIException):
            return cls._classify_api_error(cause)
        return None


def _exception_chain(error: Exception) -> list[Exception]:
    chain: list[Exception] = []
    current: BaseException | None = error
    while isinstance(current, Exception) and current not in chain:
        chain.append(current)
        current = current.__cause__ or (None if current.__suppress_context__ else current.__context__)
    return chain
