"""Surface safe user-facing messages for alert check failures.

Thin adapter over `posthog.errors.classify_query_error` — maps the existing
category enum to alert-specific messages. Raw exception text still goes to
Sentry via `capture_exception`; this module only produces UI/Slack-safe strings.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from posthog.hogql.errors import ExposedHogQLError

from posthog.errors import ExposedCHQueryError, QueryErrorCategory, classify_query_error

AlertErrorCode = Literal["server_busy", "query_performance", "invalid_query", "cancelled", "unknown"]


@dataclass(frozen=True)
class ClassifiedAlertError:
    code: AlertErrorCode
    user_message: str


_UNKNOWN = ClassifiedAlertError(
    code="unknown",
    user_message="Alert check failed unexpectedly. PostHog has been notified.",
)


def classify(exc: Exception) -> ClassifiedAlertError:
    category = classify_query_error(exc)

    if category == QueryErrorCategory.RATE_LIMITED:
        return ClassifiedAlertError(
            code="server_busy",
            user_message="PostHog is temporarily busy. The alert check will retry automatically.",
        )

    if category == QueryErrorCategory.QUERY_PERFORMANCE_ERROR:
        return ClassifiedAlertError(
            code="query_performance",
            user_message="Query is too expensive. Try narrower filters or a shorter window.",
        )

    if category == QueryErrorCategory.USER_ERROR:
        # Only expose the message text when the exception type guarantees sanitization —
        # ExposedCHQueryError.__str__ strips DB::Exception / Stack trace framing, and
        # ExposedHogQLError carries an explicit user-safe message. Many ClickHouse error
        # codes carry USER_ERROR category but ship as raw InternalCHQueryError (via
        # wrap_clickhouse_query_error) with the full DB::Exception text intact — fall
        # those through to the generic unknown message rather than leaking internals.
        if isinstance(exc, ExposedCHQueryError | ExposedHogQLError):
            return ClassifiedAlertError(code="invalid_query", user_message=str(exc)[:500])
        return _UNKNOWN

    if category == QueryErrorCategory.CANCELLED:
        return ClassifiedAlertError(
            code="cancelled",
            user_message="Alert check was cancelled. It will retry automatically.",
        )

    return _UNKNOWN
