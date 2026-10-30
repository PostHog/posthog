"""A scanner's recording filter that cannot run: telling it apart from a transient failure, and recording it."""

import datetime as dt

from django.utils import timezone

from clickhouse_driver.errors import ServerException

from posthog.hogql.errors import ExposedHogQLError

from posthog.errors import QueryErrorCategory, classify_query_error

from products.replay_vision.backend.models.replay_scanner import ReplayScanner

# A filter error usually needs a person to edit the filter, but our own query building can be the
# cause too, so the sweep tries the filter again after this long rather than never.
FILTER_ERROR_RECHECK = dt.timedelta(hours=6)

_MAX_MESSAGE_LENGTH = 1000


def filter_error_message(error: BaseException) -> str | None:
    """The user-facing reason the filter cannot run, or None when the error is not about the filter."""
    if isinstance(error, ExposedHogQLError):
        message = str(error)
    elif isinstance(error, ServerException) and classify_query_error(error) == QueryErrorCategory.USER_ERROR:
        message = str(error)
    else:
        return None
    return message[:_MAX_MESSAGE_LENGTH] or "The filter cannot run."


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


def clear_filter_error(scanner: ReplayScanner) -> None:
    if scanner.filter_error_at is None:
        return
    ReplayScanner.all_origins.filter(pk=scanner.pk).update(filter_error=None, filter_error_at=None)
    scanner.filter_error = None
    scanner.filter_error_at = None
