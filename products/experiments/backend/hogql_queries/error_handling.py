"""
Centralized error handling for experiments to ensure users see friendly error messages
while technical details are logged for engineers.
"""

import functools
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Optional, TypeVar, cast

import structlog
from clickhouse_driver.errors import ServerException
from rest_framework.exceptions import ValidationError

from posthog.hogql.errors import ExposedHogQLError, InternalHogQLError

from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.errors import ExposedCHQueryError, QueryErrorCategory, look_up_clickhouse_error_code_meta
from posthog.event_usage import groups
from posthog.exceptions import (
    ClickHouseAtCapacity,
    ClickHouseEstimatedQueryExecutionTimeTooLong,
    ClickHouseQueryMemoryLimitExceeded,
    ClickHouseQueryTimeOut,
)
from posthog.exceptions_capture import capture_exception
from posthog.ph_client import ph_scoped_capture

from products.experiments.stats.shared.statistics import StatisticError

if TYPE_CHECKING:
    from posthog.models.team import Team
    from posthog.models.user import User

# Map error types to their error codes for the API response
ERROR_TYPE_TO_CODE: dict[type, str] = {
    ClickHouseQueryMemoryLimitExceeded: "memory_limit_exceeded",
}

_MAX_ERROR_EVENT_MESSAGE_LENGTH = 500

logger = structlog.get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

# User-friendly error messages for specific error types
# Note: ValueError and generic Exception are intentionally excluded - they pass through unaltered
# so the original error message is visible for debugging
ERROR_TYPE_MESSAGES: dict[type, str] = {
    # Statistical calculation errors
    StatisticError: "Unable to calculate experiment statistics. Please ensure your experiment has sufficient data and try again.",
    # HogQL/Query errors
    InternalHogQLError: "Unable to process your experiment query. Please check your metric configuration and try again.",
    ExposedCHQueryError: "Unable to retrieve experiment data. Please try refreshing the page.",
    # ClickHouse resource errors
    ClickHouseQueryMemoryLimitExceeded: "This experiment query is using too much memory. Try viewing a shorter time period or contact support for help.",
    # Python built-in errors that can occur during calculation
    ZeroDivisionError: "Unable to calculate results due to insufficient data. Please wait for more experiment data.",
}


def get_user_friendly_message(error: Exception) -> str | None:
    """Convert technical error messages to user-friendly ones based on error type.
    Returns None if the error type is not in the mapping (should be re-raised as-is).
    """

    error_type = type(error)

    # If a ValidationError is raised, we can return the message directly
    if error_type is ValidationError:
        validation_error = cast(ValidationError, error)
        if isinstance(validation_error.detail, list) and validation_error.detail:
            return str(validation_error.detail[0])
        elif isinstance(validation_error.detail, dict):
            # For dict-style errors, get the first error message
            if not validation_error.detail:
                return "Validation error occurred"
            first_key = next(iter(validation_error.detail))
            detail_value = validation_error.detail[first_key]
            if isinstance(detail_value, list) and detail_value:
                return str(detail_value[0])
            else:
                return str(detail_value)
        else:
            return str(validation_error.detail)

    # Look for exact type match first
    if error_type in ERROR_TYPE_MESSAGES:
        return ERROR_TYPE_MESSAGES[error_type]

    # Check if error is an instance of any of the registered types
    for registered_type, message in ERROR_TYPE_MESSAGES.items():
        if isinstance(error, registered_type):
            return message

    return None


def classify_experiment_query_error(error: Exception) -> str:
    """Single failure taxonomy for the `experiment metric error` event, derived from the typed
    exceptions `posthog/errors.py` already produces — never from message parsing or HTTP status.

    Values: timeout · out_of_memory · byte_limit · rate_limited · insufficient_data ·
    validation_error · server_error (catch-all).
    """
    if isinstance(error, (StatisticError, ZeroDivisionError)):
        return "insufficient_data"
    if isinstance(error, (ValidationError, ExposedHogQLError)):
        return "validation_error"
    if isinstance(error, (ClickHouseQueryTimeOut, ClickHouseEstimatedQueryExecutionTimeTooLong)):
        return "timeout"
    if isinstance(error, ClickHouseQueryMemoryLimitExceeded):
        return "out_of_memory"
    if isinstance(error, (ClickHouseAtCapacity, ConcurrencyLimitExceeded)):
        return "rate_limited"
    if isinstance(error, ServerException):
        meta = look_up_clickhouse_error_code_meta(error)
        if meta.name in ("TIMEOUT_EXCEEDED", "SOCKET_TIMEOUT"):
            return "timeout"
        if meta.name == "MEMORY_LIMIT_EXCEEDED":
            return "out_of_memory"
        if meta.name in ("TOO_MANY_BYTES", "TOO_MANY_ROWS", "TOO_MANY_ROWS_OR_BYTES"):
            return "byte_limit"
        if meta.get_category() == QueryErrorCategory.RATE_LIMITED:
            return "rate_limited"
    return "server_error"


def capture_experiment_metric_error_event(
    *,
    team: "Team",
    error: Exception,
    context: str,
    mechanism: str,
    experiment_id: int | None,
    metric_uuid: str | None = None,
    metric_kind: str | None = None,
    query_kind: str | None = None,
    user: Optional["User"] = None,
    extra_properties: dict[str, Any] | None = None,
) -> None:
    """Emit the terminal `experiment metric error` product analytics event.

    Call this exactly once per user-visible failure, from the layer that owns retries for its
    execution path (the runner where nothing above retries; the orchestrator's final attempt
    otherwise). Telemetry must never fail the caller, so any capture error is swallowed.
    """
    try:
        distinct_id = user.distinct_id if user is not None and user.distinct_id else f"team_{team.id}"
        with ph_scoped_capture() as capture:
            capture(
                distinct_id=distinct_id,
                event="experiment metric error",
                properties={
                    "experiment_id": experiment_id,
                    "team_id": team.id,
                    "metric_uuid": metric_uuid,
                    "metric_kind": metric_kind,
                    "query_kind": query_kind,
                    "error_type": classify_experiment_query_error(error),
                    "error_message": str(error)[:_MAX_ERROR_EVENT_MESSAGE_LENGTH],
                    "context": context,
                    "mechanism": mechanism,
                    **(extra_properties or {}),
                },
                groups=groups(organization=team.organization, team=team),
            )
    except Exception:
        logger.warning(
            "experiment_metric_error_event_capture_failed",
            experiment_id=experiment_id,
            metric_uuid=metric_uuid,
            exc_info=True,
        )


def _emit_runner_terminal_error_event(runner: Any, error: Exception) -> None:
    """Emit the terminal failure event for a query runner on the direct (in-request) path.

    Gated on the runner's `error_event_context` ("ui"/"agent"; None = silent) AND `user_facing`
    (internal callers — recalc, canary, warming — own their retries, so a runner-level emit there
    would count non-terminal attempts). One runner execution is terminal on every direct path:
    the frontend has no automatic retry loop and the async Celery task swallows failures
    (no retry passes back through the runner).
    """
    if runner is None:
        return
    context = getattr(runner, "error_event_context", None)
    if not context or not getattr(runner, "user_facing", True):
        return
    team = getattr(runner, "team", None)
    if team is None:
        return

    experiment_id = getattr(runner, "experiment_id", None)
    if experiment_id is None:
        experiment_id = getattr(getattr(runner, "experiment", None), "id", None)
    metric = getattr(runner, "metric", None)
    query = getattr(runner, "query", None)

    capture_experiment_metric_error_event(
        team=team,
        error=error,
        context=context,
        mechanism="direct",
        experiment_id=experiment_id,
        metric_uuid=getattr(metric, "uuid", None),
        metric_kind=getattr(metric, "metric_type", None),
        query_kind=type(query).__name__ if query is not None else None,
        user=getattr(runner, "user", None),
    )


def experiment_error_handler(method: F) -> F:
    """
    Decorator that catches technical errors, logs them for engineers,
    and raises user-friendly errors for the frontend.
    """

    @functools.wraps(method)
    def wrapper(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except (ValidationError, ExposedHogQLError) as e:
            # ValidationErrors and ExposedHogQLErrors are already user-facing, let them through.
            # Still terminal user pain (the metric fails to load every time), so still counted.
            _emit_runner_terminal_error_event(args[0] if args else None, e)
            raise
        except Exception as e:
            # Get context for logging
            self = args[0] if args else None

            experiment_id = getattr(self, "experiment_id", None)
            if experiment_id is None:
                experiment = getattr(self, "experiment", None)
                if experiment is not None:
                    experiment_id = getattr(experiment, "id", None)

            metric = getattr(self, "metric", None)
            if metric:
                metric_type = type(metric).__name__
            else:
                metric_type = None

            query_runner = type(self).__name__ if self is not None else None

            # Log the technical error for engineers
            logger.error(
                "Experiment calculation error",
                experiment_id=experiment_id,
                metric_type=metric_type,
                query_runner=query_runner,
                error_type=type(e).__name__,
                error_message=str(e),
                error_detail=getattr(e, "detail", None),
                exc_info=True,
            )

            # Capture exception for error tracking
            capture_exception(
                e,
                additional_properties={
                    "experiment_id": experiment_id,
                    "metric_type": metric_type,
                    "query_runner": query_runner,
                    "method": method.__name__,
                },
            )

            _emit_runner_terminal_error_event(self, e)

            # If this is not user-facing, re-raise the original exception after logging/capturing
            user_facing = True
            if self is not None:
                user_facing = getattr(self, "user_facing", True)
            if not user_facing:
                # Preserve original exception for internal callers
                raise

            # Convert to user-friendly error if we have a mapping, otherwise re-raise as-is
            user_message = get_user_friendly_message(e)
            if user_message is None:
                raise

            # Get error code if available
            error_code = ERROR_TYPE_TO_CODE.get(type(e))
            raise ValidationError(user_message, code=error_code)

    return cast(F, wrapper)
