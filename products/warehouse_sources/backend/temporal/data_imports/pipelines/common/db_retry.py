import time
from collections.abc import Callable
from typing import ParamSpec, TypeVar

from django.db import InternalError, OperationalError, close_old_connections

from posthog.temporal.common.db_errors import is_transient_db_error

_P = ParamSpec("_P")
_R = TypeVar("_R")

_MAX_ATTEMPTS = 4


def _backoff_sleep(attempt: int) -> None:
    """Linear growth capped at 30s (2s, 4s, 6s, ...), matching OAuthMixin.get_oauth_integration."""
    time.sleep(min(2 * attempt, 30))


def retry_on_operational_error(fn: Callable[_P, _R]) -> Callable[_P, _R]:
    """Retry a synchronous, idempotent DB operation on a transient DB error.

    Temporal activities run in a long-lived worker outside Django's request cycle, so a pooled
    Postgres connection can be closed server-side while idle, or the connection pooler can reject
    a query with a wait timeout (`query_wait_timeout`) when the pool is saturated. Both surface as
    a transient ``OperationalError`` that clears once a healthy connection is used. A primary/
    replica failover surfaces differently — Postgres rejects the write with "read-only
    transaction", which Django wraps as ``InternalError`` — so that case is only retried when
    ``is_transient_db_error`` recognizes it, to avoid masking genuine ``InternalError`` bugs.
    ``close_old_connections()`` evicts a connection a failed query marked unusable so the next
    attempt runs on a fresh one; the backoff gives a saturated pool (or an in-progress failover)
    time to clear rather than retrying straight back into the same failure. Only wrap idempotent
    operations — each attempt re-runs ``fn`` from scratch.
    """

    def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> _R:
        attempt = 0
        while True:
            try:
                return fn(*args, **kwargs)
            except (OperationalError, InternalError) as e:
                if isinstance(e, InternalError) and not is_transient_db_error(e):
                    raise
                attempt += 1
                if attempt >= _MAX_ATTEMPTS:
                    raise
                close_old_connections()
                _backoff_sleep(attempt)

    return wrapper
