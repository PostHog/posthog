"""Classify transient Postgres pool errors so callers can retry or avoid paging them.

A momentary PgBouncer pool-saturation blip hits every activity that touches Postgres at once, and
each one recovers on its own once the pool drains — unlike a genuine query bug. Callers use this to
decide whether to retry inline and whether to report a failure to error tracking.
"""

from django.db import OperationalError

# PgBouncer kills a query that waited too long for a pooled connection with `query_wait_timeout`,
# and surfaces a dropped/reset backend connection as one of the other two markers.
_TRANSIENT_DB_ERROR_MARKERS = (
    "query_wait_timeout",
    "server closed the connection unexpectedly",
    "connection failed",
)


def is_transient_db_error(error: BaseException) -> bool:
    return isinstance(error, OperationalError) and any(marker in str(error) for marker in _TRANSIENT_DB_ERROR_MARKERS)


__all__ = ["is_transient_db_error"]
