from ssl import SSLError

from django.db import OperationalError

from billiard.exceptions import SoftTimeLimitExceeded
from clickhouse_driver.errors import SocketTimeoutError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from rest_framework.exceptions import ValidationError
from urllib3.exceptions import MaxRetryError, ProtocolError, ReadTimeoutError

from posthog.hogql.errors import (
    QueryError,
    ResolutionError,
    SyntaxError as HogQLSyntaxError,
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
    ClickHouseQueryMemoryLimitExceeded,
    ClickHouseQuerySizeExceeded,
    ClickHouseQueryTimeOut,
)

# =============================================================================
# Export Failure Classification
# =============================================================================
#
# failure_type values stored on ExportedAsset:
#   - "user": Errors the user can fix by modifying their query or reducing scope
#   - "system": Infrastructure/capacity errors that may resolve with retries
#   - "timeout_generation": Export timed out during asset generation
#   - "unknown": Errors needing investigation to properly classify
#
# These tuples are authoritative. Historical rows have best-effort accuracy.
# =============================================================================

FAILURE_TYPE_USER = "user"
FAILURE_TYPE_SYSTEM = "system"
FAILURE_TYPE_TIMEOUT_GENERATION = "timeout_generation"
FAILURE_TYPE_UNKNOWN = "unknown"


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


EXCEPTIONS_TO_RETRY = (
    *CH_TRANSIENT_ERRORS,
    OperationalError,
    ProtocolError,
    ConcurrencyLimitExceeded,
    MaxRetryError,  # This is from urllib, e.g. HTTP retries instead of "job retries"
    ReadTimeoutError,  # Network timeout from urllib3
    ClickHouseAtCapacity,
    SocketTimeoutError,
    SSLError,
    BrowserlessUnavailable,
)

USER_QUERY_ERRORS = (
    QueryError,
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
    PlaywrightTimeoutError,
    ExportCancelled,
)

# Exception class names for string-based classification (used in backfill)
USER_QUERY_ERROR_NAMES = frozenset(cls.__name__ for cls in USER_QUERY_ERRORS)
SYSTEM_ERROR_NAMES = frozenset(cls.__name__ for cls in EXCEPTIONS_TO_RETRY)
# "TimeoutException" kept literally: historical ExportedAsset rows from the retired selenium
# render path stored that exception name and must still classify as timeouts.
TIMEOUT_ERROR_NAMES = frozenset(cls.__name__ for cls in TIMEOUT_ERRORS) | {"TimeoutException"}


def classify_failure_type(exception: Exception | str) -> str:
    # Live exceptions are classified by actual type, not name: the name sets are derived from
    # these same tuples, so isinstance has identical coverage while avoiding false positives from
    # unrelated classes that merely share a name (django/pydantic ValidationError, builtin SyntaxError).
    if isinstance(exception, Exception):
        if isinstance(exception, TIMEOUT_ERRORS):
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
