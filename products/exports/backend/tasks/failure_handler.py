import sys
from ssl import SSLError
from typing import TypedDict

from django.db import OperationalError

from billiard.exceptions import SoftTimeLimitExceeded
from clickhouse_driver.errors import SocketTimeoutError
from rest_framework.exceptions import ValidationError
from urllib3.exceptions import MaxRetryError, ProtocolError, ReadTimeoutError

from posthog.hogql.errors import (
    QueryError,
    ResolutionError,
    SyntaxError as HogQLSyntaxError,
    TableAccessDeniedError,
)

from posthog.clickhouse.client.limit import ConcurrencyLimitExceeded
from posthog.errors import (
    CH_TRANSIENT_ERRORS,
    CHQueryErrorCannotParseUuid,
    CHQueryErrorIllegalAggregation,
    CHQueryErrorIllegalTypeOfArgument,
    CHQueryErrorInvalidJoinOnExpression,
    CHQueryErrorNoCommonType,
    CHQueryErrorNotAnAggregate,
    CHQueryErrorNumberOfArgumentsDoesntMatch,
    CHQueryErrorTooManyBytes,
    CHQueryErrorTypeMismatch,
    CHQueryErrorUnknownFunction,
    CHQueryErrorUnknownIdentifier,
    CHQueryErrorUnknownTable,
    CHQueryErrorUnsupportedMethod,
)
from posthog.exceptions import (
    ClickHouseAtCapacity,
    ClickHouseClusterMemoryLimitExceeded,
    ClickHouseQueryMemoryLimitExceeded,
    ClickHouseQuerySizeExceeded,
    ClickHouseQueryTimeOut,
)
from posthog.storage.object_storage import ObjectStorageError

# =============================================================================
# Export Failure Classification
# =============================================================================
#
# failure_type values stored on ExportedAsset:
#   - "user": Errors the user can fix by modifying their query or reducing scope
#   - "system": Infrastructure/capacity errors that may resolve with retries
#   - "timeout_generation": Export timed out during asset generation
#   - "renderer_unknown": The video renderer crashed with an exception it has no code for
#   - "other": The in-browser player reported an error code the renderer doesn't recognize
#   - "unknown": Errors needing investigation to properly classify
#
# These tuples are authoritative. Historical rows have best-effort accuracy.
# =============================================================================

FAILURE_TYPE_USER = "user"
FAILURE_TYPE_SYSTEM = "system"
FAILURE_TYPE_TIMEOUT_GENERATION = "timeout_generation"
FAILURE_TYPE_RENDERER_UNKNOWN = "renderer_unknown"
FAILURE_TYPE_OTHER = "other"
FAILURE_TYPE_UNKNOWN = "unknown"

# Low-cardinality dimensions for SLO events. Keep these stable: they are intended
# for breakdowns and alerts, unlike exception messages or stack traces.
SLO_FAILURE_CATEGORY_RENDERER_RATE_LIMITED = "renderer_rate_limited"
SLO_FAILURE_CATEGORY_RENDERER_UNAVAILABLE = "renderer_unavailable"
SLO_FAILURE_CATEGORY_RENDERER_TIMEOUT = "renderer_timeout"
SLO_FAILURE_CATEGORY_QUERY = "query"
SLO_FAILURE_CATEGORY_QUERY_CAPACITY = "query_capacity"
SLO_FAILURE_CATEGORY_STORAGE = "storage"
SLO_FAILURE_CATEGORY_TRANSIENT_DEPENDENCY = "transient_dependency"
SLO_FAILURE_CATEGORY_APPLICATION = "application"
SLO_FAILURE_CATEGORY_ACTIVITY_TIMEOUT = "activity_timeout"

SLO_FAILURE_COMPONENT_BROWSERLESS = "browserless"
SLO_FAILURE_COMPONENT_QUERY = "query"
SLO_FAILURE_COMPONENT_STORAGE = "object_storage"
SLO_FAILURE_COMPONENT_DEPENDENCY = "dependency"
SLO_FAILURE_COMPONENT_EXPORTER = "exporter"
SLO_FAILURE_COMPONENT_EXPORT_WORKER = "export_worker"


class ExportFailureDetails(TypedDict):
    failure_category: str
    failure_component: str
    failure_retryable: bool


RATE_LIMIT_MESSAGE_PREFIX_CHARS = 8_000

# Video renders fail with a code from the recording rasterizer rather than a Python exception, so they
# classify by code (RASTERIZATION_ERROR_CODES in
# nodejs/src/session-replay/recording-rasterizer/errors.ts). A code absent here classifies as
# "unknown", which is the signal to add it rather than a bucket to grow silently.
RASTERIZATION_CODE_TO_FAILURE_TYPE: dict[str, str] = {
    "TIMEOUT": FAILURE_TYPE_TIMEOUT_GENERATION,
    "CAPTURE_ABORTED": FAILURE_TYPE_TIMEOUT_GENERATION,
    "BEGINFRAME_DEADLOCK": FAILURE_TYPE_TIMEOUT_GENERATION,
    # A property of the recording or the request rather than a fault in our infrastructure. Bucketing
    # these as "system" would put them in front of whoever watches infra alerts.
    "NO_SNAPSHOTS": FAILURE_TYPE_USER,
    "INVALID_INPUT": FAILURE_TYPE_USER,
    "RECORDING_TOO_LARGE": FAILURE_TYPE_USER,
    # Reaching the recording's data failed, which nobody exporting it can do anything about.
    "DATA_LOAD_FAILED": FAILURE_TYPE_SYSTEM,
    "S3_UPLOAD_UNDECODABLE_RESPONSE": FAILURE_TYPE_SYSTEM,
    "S3_UPLOAD_FAILED": FAILURE_TYPE_SYSTEM,
    "INIT_FAILED": FAILURE_TYPE_SYSTEM,
    "BLOCK_LISTING_FAILED": FAILURE_TYPE_SYSTEM,
    "TARGET_CLOSED": FAILURE_TYPE_SYSTEM,
    # The render activity died without producing a code at all: heartbeat or start-to-close timeout
    # from a lost or wedged worker. Not the renderer's own TIMEOUT, but still a render that ran out
    # of time. Resolved in the workflow's _record_failure, not a rasterizer code.
    "ACTIVITY_TIMEOUT": FAILURE_TYPE_TIMEOUT_GENERATION,
    # The renderer's own catch-all codes get their own buckets so "unknown" keeps meaning exactly
    # one thing: a code missing from this map that someone needs to add.
    "UNKNOWN": FAILURE_TYPE_RENDERER_UNKNOWN,
    "OTHER": FAILURE_TYPE_OTHER,
}

# Shown to whoever asked for the export, so each one says what happened and what to do next. A
# recording with no data will never render, so telling that user to retry would send them in a loop.
_RASTERIZATION_MESSAGES: dict[str, str] = {
    "TIMEOUT": "This recording took too long to render. Try exporting a shorter part of it.",
    "CAPTURE_ABORTED": "The render stopped before it finished. Try exporting a shorter part of the recording.",
    "BEGINFRAME_DEADLOCK": "The render stopped responding. Try exporting a shorter part of the recording.",
    "NO_SNAPSHOTS": "This recording has no playable data, so there is nothing to export.",
    "INVALID_INPUT": "This export request was not valid. Contact support if it keeps happening.",
    "RECORDING_TOO_LARGE": "This recording is too large to render as a video.",
    "DATA_LOAD_FAILED": "We could not load this recording's data. Try the export again in a few minutes.",
    "S3_UPLOAD_UNDECODABLE_RESPONSE": "The finished video could not be saved. Try the export again.",
    "S3_UPLOAD_FAILED": "The finished video could not be saved. Try the export again.",
    "INIT_FAILED": "The video renderer could not start. Try the export again.",
    "BLOCK_LISTING_FAILED": "We could not read this recording. Try the export again in a few minutes.",
    "TARGET_CLOSED": "The video renderer stopped before it finished. Try the export again.",
    "ACTIVITY_TIMEOUT": "This recording took too long to render. Try exporting a shorter part of it.",
}

_RASTERIZATION_FALLBACK_MESSAGE = "The video export failed. Try again, and contact support if it keeps failing."


def classify_rasterization_failure(error_code: str | None) -> str:
    return RASTERIZATION_CODE_TO_FAILURE_TYPE.get(error_code or "", FAILURE_TYPE_UNKNOWN)


def rasterization_failure_message(error_code: str | None) -> str:
    return _RASTERIZATION_MESSAGES.get(error_code or "", _RASTERIZATION_FALLBACK_MESSAGE)


class ExportCancelled(Exception):
    """Raised when an export is canceled due to timeout."""

    pass


class BrowserlessUnavailable(Exception):
    """Raised when the browserless.io render backend is unreachable or drops the connection."""

    pass


class ExcelColumnLimitExceeded(Exception):
    """Raised when export data exceeds openpyxl's 18,278 column limit (ZZZ)."""

    def __init__(self, message: str | None = None):
        super().__init__(
            message
            or "Export exceeds the maximum of 18,278 columns. Try exporting fewer columns or use CSV format instead."
        )


class InvalidExportContext(Exception):
    """Raised when an export's export_context lacks a renderable target."""

    pass


class RetryableExportError(Exception):
    pass


EXCEPTIONS_TO_RETRY = (
    *CH_TRANSIENT_ERRORS,
    OperationalError,
    ProtocolError,
    ConcurrencyLimitExceeded,
    MaxRetryError,  # This is from urllib, e.g. HTTP retries instead of "job retries"
    ReadTimeoutError,  # Network timeout from urllib3
    SocketTimeoutError,
    SSLError,
    BrowserlessUnavailable,
    ObjectStorageError,
    RetryableExportError,
)

USER_QUERY_ERRORS = (
    QueryError,
    # A QueryError subclass, so isinstance already covers it. Listed so the derived name set covers
    # it too: an export failure crosses the Temporal activity boundary as a class name.
    TableAccessDeniedError,
    HogQLSyntaxError,
    ValidationError,  # DRF validation of the user's query (e.g. a funnel with fewer than two steps)
    ClickHouseQueryMemoryLimitExceeded,  # Users should reduce the date range on their query (or materialise)
    ClickHouseQueryTimeOut,  # Users should switch to materialised queries if they run into this
    CHQueryErrorIllegalTypeOfArgument,
    CHQueryErrorNoCommonType,
    CHQueryErrorNotAnAggregate,
    CHQueryErrorUnknownFunction,
    CHQueryErrorTypeMismatch,
    CHQueryErrorIllegalAggregation,
    CHQueryErrorNumberOfArgumentsDoesntMatch,
    CHQueryErrorUnknownIdentifier,
    CHQueryErrorTooManyBytes,
    CHQueryErrorCannotParseUuid,
    ClickHouseQuerySizeExceeded,
    CHQueryErrorUnsupportedMethod,
    ResolutionError,
    CHQueryErrorInvalidJoinOnExpression,
    CHQueryErrorUnknownTable,
    ExcelColumnLimitExceeded,
    InvalidExportContext,
)

TIMEOUT_ERRORS = (
    SoftTimeLimitExceeded,
    TimeoutError,
    ExportCancelled,
)

# Exception class names for string-based classification (used in backfill)
USER_QUERY_ERROR_NAMES = frozenset(cls.__name__ for cls in USER_QUERY_ERRORS)
SYSTEM_ERROR_NAMES = frozenset(cls.__name__ for cls in EXCEPTIONS_TO_RETRY)
# "TimeoutException" kept literally: historical ExportedAsset rows from the retired selenium
# render path stored that exception name and must still classify as timeouts.
# playwright's TimeoutError.__name__ is also "TimeoutError" (aliased on import), so it's already
# covered here without needing the class itself.
TIMEOUT_ERROR_NAMES = frozenset(cls.__name__ for cls in TIMEOUT_ERRORS) | {"TimeoutException"}

# Capacity saturation, not a fault in the query itself: query-scheduling limits and server-wide or
# per-user memory pressure. posthog.errors.classify_query_error groups the same three as
# RATE_LIMITED, so keep this set aligned — otherwise a single capacity incident splits across the
# query and transient_dependency categories instead of aggregating under query_capacity.
QUERY_CAPACITY_ERROR_NAMES = frozenset(
    cls.__name__ for cls in (ConcurrencyLimitExceeded, ClickHouseAtCapacity, ClickHouseClusterMemoryLimitExceeded)
)


def _is_playwright_timeout(exception: BaseException) -> bool:
    # playwright is a heavy import (browser automation), only needed by the actual image-export
    # path. isinstance() against it can't be a real match unless something has already imported
    # playwright.sync_api (raising one requires it), so checking sys.modules first avoids paying
    # the import cost on every failure-classification call. getattr with a default covers the
    # window where another thread has started (but not finished) that first import: sys.modules
    # holds a partially initialized module then, which may not expose TimeoutError yet — and an
    # exception raised by playwright itself cannot predate its own module finishing import.
    playwright_sync_api = sys.modules.get("playwright.sync_api")
    if playwright_sync_api is None:
        return False
    timeout_error = getattr(playwright_sync_api, "TimeoutError", None)
    return timeout_error is not None and isinstance(exception, timeout_error)


def classify_failure_type(exception: Exception | str) -> str:
    # Live exceptions are classified by actual type, not name: the name sets are derived from
    # these same tuples, so isinstance has identical coverage while avoiding false positives from
    # unrelated classes that merely share a name (django/pydantic ValidationError, builtin SyntaxError).
    if isinstance(exception, Exception):
        if isinstance(exception, TIMEOUT_ERRORS) or _is_playwright_timeout(exception):
            return FAILURE_TYPE_TIMEOUT_GENERATION
        if isinstance(exception, USER_QUERY_ERRORS):
            return FAILURE_TYPE_USER
        if isinstance(exception, EXCEPTIONS_TO_RETRY):
            return FAILURE_TYPE_SYSTEM
        return FAILURE_TYPE_UNKNOWN

    # Stored exception-class names (historical rows, backfill) only carry the name, so fall back to
    # name matching. This is best-effort and can't distinguish same-named classes from other packages.
    exception_type = exception
    if exception_type:
        if exception_type in TIMEOUT_ERROR_NAMES:
            return FAILURE_TYPE_TIMEOUT_GENERATION
        if exception_type in USER_QUERY_ERROR_NAMES:
            return FAILURE_TYPE_USER
        if exception_type in SYSTEM_ERROR_NAMES:
            return FAILURE_TYPE_SYSTEM
    return FAILURE_TYPE_UNKNOWN


def is_user_query_error_type(exception_type: str | None) -> bool:
    if exception_type is None:
        return False
    return classify_failure_type(exception_type) == FAILURE_TYPE_USER


def export_slo_failure_details(exception: Exception | str) -> ExportFailureDetails:
    """Return safe, low-cardinality SLO dimensions for an export failure.

    This deliberately does not include the exception message. It is emitted on
    every failed export/subscription SLO and must be safe to aggregate broadly.
    """

    exception_type = type(exception).__name__ if isinstance(exception, Exception) else exception
    message = str(exception)[:RATE_LIMIT_MESSAGE_PREFIX_CHARS].lower() if isinstance(exception, Exception) else ""

    if exception_type == BrowserlessUnavailable.__name__:
        if any(marker in message for marker in ("429", "too many requests", "rate limit", "rate_limited")):
            return {
                "failure_category": SLO_FAILURE_CATEGORY_RENDERER_RATE_LIMITED,
                "failure_component": SLO_FAILURE_COMPONENT_BROWSERLESS,
                "failure_retryable": True,
            }
        return {
            "failure_category": SLO_FAILURE_CATEGORY_RENDERER_UNAVAILABLE,
            "failure_component": SLO_FAILURE_COMPONENT_BROWSERLESS,
            "failure_retryable": True,
        }

    if exception_type in TIMEOUT_ERROR_NAMES:
        return {
            "failure_category": SLO_FAILURE_CATEGORY_RENDERER_TIMEOUT,
            "failure_component": SLO_FAILURE_COMPONENT_BROWSERLESS,
            "failure_retryable": exception_type != ExportCancelled.__name__,
        }

    if exception_type in QUERY_CAPACITY_ERROR_NAMES:
        return {
            "failure_category": SLO_FAILURE_CATEGORY_QUERY_CAPACITY,
            "failure_component": SLO_FAILURE_COMPONENT_QUERY,
            "failure_retryable": True,
        }

    if exception_type == ObjectStorageError.__name__ or "s3" in exception_type.lower():
        return {
            "failure_category": SLO_FAILURE_CATEGORY_STORAGE,
            "failure_component": SLO_FAILURE_COMPONENT_STORAGE,
            "failure_retryable": True,
        }

    failure_type = classify_failure_type(exception)
    if failure_type == FAILURE_TYPE_USER:
        return {
            "failure_category": SLO_FAILURE_CATEGORY_QUERY,
            "failure_component": SLO_FAILURE_COMPONENT_QUERY,
            "failure_retryable": False,
        }
    if failure_type == FAILURE_TYPE_SYSTEM:
        return {
            "failure_category": SLO_FAILURE_CATEGORY_TRANSIENT_DEPENDENCY,
            "failure_component": SLO_FAILURE_COMPONENT_DEPENDENCY,
            "failure_retryable": True,
        }
    return {
        "failure_category": SLO_FAILURE_CATEGORY_APPLICATION,
        "failure_component": SLO_FAILURE_COMPONENT_EXPORTER,
        "failure_retryable": False,
    }
