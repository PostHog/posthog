from enum import StrEnum

from clickhouse_driver.errors import ServerException
from temporalio.exceptions import ApplicationError

from posthog.errors import QueryErrorCategory, look_up_clickhouse_error_code_meta
from posthog.exceptions import ClickHouseAtCapacity, ClickHouseQueryTimeOut

from products.replay_vision.backend.error_kinds import FailureKind, IneligibleSessionKind

__all__ = [
    "INELIGIBLE_SESSION_ERROR_TYPE",
    "SCANNER_FAILURE_ERROR_TYPE",
    "TRANSIENT_QUERY_ERROR_TYPE",
    "ConsentWithdrawnError",
    "FailureKind",
    "IneligibleSessionError",
    "IneligibleSessionKind",
    "ScannerFailureError",
    "TransientQueryError",
    "as_transient_query_error",
]

# Strings survive Temporal's ActivityError wrapping via ApplicationError.type, so the
# workflow can dispatch on them without parsing exception messages.
INELIGIBLE_SESSION_ERROR_TYPE = "IneligibleSession"
SCANNER_FAILURE_ERROR_TYPE = "ScannerFailure"
TRANSIENT_QUERY_ERROR_TYPE = "TransientQuery"


class _KindedApplicationError(ApplicationError):
    """ApplicationError carrying a typed `kind` payload that survives Temporal's serialization.

    `details=(kind,)` is the canonical way to attach a typed payload an outer workflow can read off
    `cause.details` after Temporal wraps the activity raise in ActivityError.
    """

    def __init__(self, message: str, *, kind: StrEnum, type: str, non_retryable: bool = True) -> None:
        super().__init__(message, str(kind), type=type, non_retryable=non_retryable)
        self.kind = kind


class IneligibleSessionError(_KindedApplicationError):
    """The session doesn't qualify for analysis. Surfaced as ObservationStatus.INELIGIBLE, not FAILED."""

    def __init__(self, message: str, *, kind: IneligibleSessionKind) -> None:
        super().__init__(message, kind=kind, type=INELIGIBLE_SESSION_ERROR_TYPE)


class ScannerFailureError(_KindedApplicationError):
    """A classified workflow failure. Surfaced as ObservationStatus.FAILED with the kind label on the frontend."""

    def __init__(self, message: str, *, kind: FailureKind) -> None:
        super().__init__(message, kind=kind, type=SCANNER_FAILURE_ERROR_TYPE, non_retryable=not kind.is_retryable)


class _QueryKind(StrEnum):
    # Deliberately outside FailureKind: this classifies an infrastructure blip on a scanner's own
    # ClickHouse query, never an observation, so it stays off the DB `error_reason` taxonomy.
    CLICKHOUSE_TRANSIENT = "clickhouse_transient"
    CLICKHOUSE_TIMEOUT = "clickhouse_timeout"


class TransientQueryError(_KindedApplicationError):
    """A ClickHouse-side blip on a scanner query. Retryable: the query itself isn't doomed."""

    def __init__(self, message: str, *, kind: _QueryKind) -> None:
        super().__init__(message, kind=kind, type=TRANSIENT_QUERY_ERROR_TYPE, non_retryable=False)


# Transport failures — 209 SOCKET_TIMEOUT and 210 NETWORK_ERROR say nothing about the query itself,
# the same reading the notebooks frame relay gives them. Cancellations and capacity rejections come
# from the shared category classification instead of a code list.
_TRANSIENT_CLICKHOUSE_CODES = frozenset({209, 210})
_TRANSIENT_CATEGORIES = frozenset({QueryErrorCategory.CANCELLED, QueryErrorCategory.RATE_LIMITED})


def as_transient_query_error(exc: Exception) -> TransientQueryError | None:
    """Classify a ClickHouse failure as a retryable blip, or None when the query is genuinely at fault.

    Only the infrastructure-side outcomes qualify. A memory or size limit, a syntax error, or an
    over-broad query is doomed on every attempt and must stay a hard failure.
    """
    if isinstance(exc, ClickHouseQueryTimeOut):
        # Our own max_execution_time ceiling. Load-dependent, so a later attempt can still land.
        return TransientQueryError(
            f"ClickHouse hit the execution time limit: {exc}", kind=_QueryKind.CLICKHOUSE_TIMEOUT
        )
    if isinstance(exc, ClickHouseAtCapacity):
        return TransientQueryError(f"ClickHouse is at capacity: {exc}", kind=_QueryKind.CLICKHOUSE_TRANSIENT)
    if not isinstance(exc, ServerException):
        return None
    meta = look_up_clickhouse_error_code_meta(exc)
    if meta.get_category() in _TRANSIENT_CATEGORIES or exc.code in _TRANSIENT_CLICKHOUSE_CODES:
        return TransientQueryError(
            f"ClickHouse ended the query early ({meta.name})", kind=_QueryKind.CLICKHOUSE_TRANSIENT
        )
    return None


class _ConsentKind(StrEnum):
    # Kept out of IneligibleSessionKind on purpose: this is a policy abort, not a session-eligibility reason,
    # so it stays off the DB `error_reason` help text / OpenAPI taxonomy. Surfaced as INELIGIBLE all the same.
    NO_AI_CONSENT = "no_ai_consent"


class ConsentWithdrawnError(_KindedApplicationError):
    """Org AI data-processing consent was withdrawn before an egress step. Surfaced as INELIGIBLE, never retried."""

    def __init__(self, message: str) -> None:
        super().__init__(message, kind=_ConsentKind.NO_AI_CONSENT, type=INELIGIBLE_SESSION_ERROR_TYPE)
