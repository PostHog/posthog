import time
from collections.abc import Callable
from typing import TypeVar

from django.db import OperationalError, close_old_connections

T = TypeVar("T")

_MAX_DB_READ_ATTEMPTS = 4


def db_read_with_retry(fn: Callable[[], T]) -> T:
    """Run an idempotent main-DB read, retrying a transient connection failure with backoff.

    Temporal activities run in a long-lived worker that never goes through Django's request
    cycle, so a pooled Postgres connection can be closed server-side while it sits idle, or the
    connection pooler can reject the query with a wait timeout when the pool is saturated. Both
    surface as a transient ``OperationalError`` and both clear once a healthy connection is used.
    ``close_old_connections()`` evicts connections already known to be stale (and, after a failed
    query marks one unusable, drops it), so each attempt runs on a fresh connection; the short
    backoff also gives a saturated pool time to drain rather than retrying straight back into the
    same wait timeout. Must run inside the ``database_sync_to_async_pool`` thread so the eviction
    targets the same connection the query uses. ``DoesNotExist`` and other errors propagate.
    """
    attempt = 0
    while True:
        close_old_connections()
        try:
            return fn()
        except OperationalError:
            attempt += 1
            if attempt >= _MAX_DB_READ_ATTEMPTS:
                raise
            time.sleep(min(2 * attempt, 30))
