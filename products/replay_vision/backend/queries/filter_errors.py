"""A scanner's recording filter that cannot run: telling it apart from a transient failure, and recording it."""

import datetime as dt

from django.utils import timezone

import structlog

from posthog.hogql.errors import ExposedHogQLError, TableAccessDeniedError

from posthog.errors import ExposedCHQueryError, QueryErrorCategory, classify_query_error

from products.replay_vision.backend.models.replay_scanner import ReplayScanner

logger = structlog.get_logger(__name__)

# A filter error usually needs a person to edit the filter, but our own query building can be the
# cause too, so the sweep tries the filter again after this long rather than never.
FILTER_ERROR_RECHECK = dt.timedelta(hours=6)

# UNKNOWN_IDENTIFIER and UNKNOWN_TABLE are user-safe but come as often from our own query building
# or a half-applied schema change, so they must not pause every scanner.
_NOT_FILTER_CODES = frozenset({47, 60})

_MAX_MESSAGE_LENGTH = 1000

# Shown in place of the reason to a viewer who cannot access the scanner's targeted experiment.
REDACTED_FILTER_ERROR = "The filter cannot run."


def filter_error_message(error: BaseException) -> str | None:
    """The user-facing reason the filter cannot run, or None when the error is not about the filter."""
    if isinstance(error, TableAccessDeniedError):
        return None
    # Rate limits and timeouts are user-safe too, so the category keeps them out.
    if isinstance(error, ExposedHogQLError) or (
        isinstance(error, ExposedCHQueryError)
        and error.code not in _NOT_FILTER_CODES
        and classify_query_error(error) == QueryErrorCategory.USER_ERROR
    ):
        return str(error)[:_MAX_MESSAGE_LENGTH] or REDACTED_FILTER_ERROR
    return None


def filter_error_pending(scanner: ReplayScanner, now: dt.datetime | None = None) -> bool:
    """Whether the scanner's filter failed recently enough that a sweep should not try it yet."""
    if scanner.filter_error_at is None:
        return False
    return (now or timezone.now()) - scanner.filter_error_at < FILTER_ERROR_RECHECK


def record_filter_error(scanner: ReplayScanner, message: str) -> None:
    now = timezone.now()
    # Matched on the version the failing run read, so a filter edited meanwhile is not marked broken.
    ReplayScanner.all_origins.filter(pk=scanner.pk, scanner_version=scanner.scanner_version).update(
        filter_error=message, filter_error_at=now
    )
    scanner.filter_error = message
    scanner.filter_error_at = now
    logger.warning(
        "replay_vision.scanner_filter_error", scanner_id=str(scanner.id), team_id=scanner.team_id, reason=message
    )


def clear_filter_error(scanner: ReplayScanner) -> None:
    if scanner.filter_error_at is None:
        return
    ReplayScanner.all_origins.filter(pk=scanner.pk, scanner_version=scanner.scanner_version).update(
        filter_error=None, filter_error_at=None
    )
    scanner.filter_error = None
    scanner.filter_error_at = None
