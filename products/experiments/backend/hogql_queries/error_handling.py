"""
Centralized error handling for experiments to ensure users see friendly error messages
while technical details are logged for engineers.
"""

import functools
from collections.abc import Callable
from typing import Any, TypeVar, cast

import structlog
from rest_framework.exceptions import ValidationError

from posthog.hogql.errors import ExposedHogQLError, InternalHogQLError

from posthog.errors import ExposedCHQueryError, QueryErrorCategory, classify_query_error
from posthog.exceptions import ClickHouseQueryMemoryLimitExceeded
from posthog.exceptions_capture import capture_exception

from products.experiments.backend.hogql_queries.utils import ExperimentDataError
from products.experiments.stats.shared.statistics import StatisticError

# Map error types to their error codes for the API response
ERROR_TYPE_TO_CODE: dict[type, str] = {
    ClickHouseQueryMemoryLimitExceeded: "memory_limit_exceeded",
}

# Error codes for ClickHouse error categories that aren't tied to a single exception class
# (e.g. the rows/bytes read-limit error is a dynamically-built CHQueryError subclass).
QUERY_ERROR_CATEGORY_TO_CODE: dict[QueryErrorCategory, str] = {
    QueryErrorCategory.QUERY_PERFORMANCE_ERROR: "query_resource_limit_exceeded",
    QueryErrorCategory.RATE_LIMITED: "query_at_capacity",
}

# User-friendly messages for ClickHouse error categories handled via classification rather
# than an exact exception-type match.
QUERY_ERROR_CATEGORY_MESSAGES: dict[QueryErrorCategory, str] = {
    QueryErrorCategory.QUERY_PERFORMANCE_ERROR: (
        "This experiment query exceeded resource limits. Try viewing a shorter time period, "
        "or contact support if the problem persists."
    ),
    QueryErrorCategory.RATE_LIMITED: "Experiment analytics are temporarily at capacity. Please refresh in a moment.",
}

logger = structlog.get_logger(__name__)

F = TypeVar("F", bound=Callable[..., Any])

# User-friendly error messages for specific error types
# Note: generic ValueError and Exception are intentionally excluded - they pass through unaltered
# so the original error message is visible for debugging. ExperimentDataError is the deliberate
# exception: it's a recognized data-shape error we want to surface gracefully, not a raw 500.
ERROR_TYPE_MESSAGES: dict[type, str] = {
    # Statistical calculation errors
    StatisticError: "Unable to calculate experiment statistics. Please ensure your experiment has sufficient data and try again.",
    # Experiment data-shape errors (e.g. no control variant in the collected data)
    ExperimentDataError: "Unable to calculate experiment results from the collected data. This usually resolves once more exposures are recorded.",
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

    # ClickHouse resource-limit, timeout, and capacity errors aren't tied to a single
    # exception class (e.g. the "rows or bytes to read exceeded" error is a dynamically-built
    # CHQueryError subclass), so fall back to query-error classification. These are transient
    # or infra conditions — degrade them to a clear, retryable message rather than surfacing a
    # raw 500 on the experiment results view.
    return QUERY_ERROR_CATEGORY_MESSAGES.get(classify_query_error(error))


def experiment_error_handler(method: F) -> F:
    """
    Decorator that catches technical errors, logs them for engineers,
    and raises user-friendly errors for the frontend.
    """

    @functools.wraps(method)
    def wrapper(*args, **kwargs):
        try:
            return method(*args, **kwargs)
        except (ValidationError, ExposedHogQLError):
            # ValidationErrors and ExposedHogQLErrors are already user-facing, let them through
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

            # Get error code if available, falling back to the query-error category for
            # classification-based messages (resource limits, capacity) that have no exact type.
            error_code = ERROR_TYPE_TO_CODE.get(type(e)) or QUERY_ERROR_CATEGORY_TO_CODE.get(classify_query_error(e))
            raise ValidationError(user_message, code=error_code)

    return cast(F, wrapper)
