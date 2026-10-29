"""Client-side statement deadline for psycopg connections.

`statement_timeout` is the server's limit, and it does not always apply. A transaction-mode pooler
can run the `SET` on one backend and the next statement on another, some Postgres-compatible
engines reject the setting, and a server that stops answering never reports a timeout at all. The
deadline here is measured on the client, so it holds in each of those cases.
"""

import os
import socket
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Self

import psycopg
import structlog
from psycopg.abc import Params, Query

logger = structlog.get_logger(__name__)

# Stable prefix of `ClientDeadlineExceededError`. `PostgresSource.get_retryable_errors` matches it,
# and no entry of `get_non_retryable_errors` may.
CLIENT_DEADLINE_ERROR = "Postgres gave no answer to a statement"

# How long the cancel request itself can take.
CANCEL_REQUEST_TIMEOUT_SECONDS = 10
# How long the statement gets to end after the cancel request, before the socket is shut down.
CANCEL_GRACE_SECONDS = 20


class ClientDeadlineExceededError(Exception):
    """A statement was still running at its client-side deadline.

    Not a psycopg error on purpose. The handlers for `QueryCanceled` read a cancel as the server's
    statement timeout, which for an incremental read is a permanent failure. This deadline acts
    only when the server limit did not, so the cause is a pooler or a server that stopped
    answering, and a later attempt can succeed.
    """

    def __init__(self, timeout_seconds: float) -> None:
        super().__init__(f"{CLIENT_DEADLINE_ERROR} within {timeout_seconds:g} seconds, so PostHog ended the statement")
        self.timeout_seconds = timeout_seconds


class _StatementWatchdog:
    def __init__(self, connection: psycopg.Connection[Any], timeout_seconds: float) -> None:
        self._connection = connection
        self._timeout_seconds = timeout_seconds
        self._lock = threading.Lock()
        self._finished = threading.Event()
        self.expired = False
        self._timer = threading.Timer(timeout_seconds, self._expire)
        self._timer.daemon = True

    def start(self) -> None:
        self._timer.start()

    def finish(self) -> None:
        self._timer.cancel()
        # Waits for a cancel request that is in flight. A request that reached the server after
        # this returned could cancel the next statement on the connection instead.
        with self._lock:
            self._finished.set()

    def _expire(self) -> None:
        with self._lock:
            if self._finished.is_set():
                return
            self.expired = True
            logger.warning("data_imports.postgres_client_deadline", timeout_seconds=self._timeout_seconds)
            try:
                self._connection.cancel_safe(timeout=CANCEL_REQUEST_TIMEOUT_SECONDS)
            except Exception as e:
                logger.debug("data_imports.postgres_client_deadline_cancel_failed", error=str(e)[:200])

        if self._finished.wait(CANCEL_GRACE_SECONDS):
            return

        # The server did not act on the cancel request. A closed socket makes the blocked read
        # fail, which the callers handle as a dropped connection.
        with self._lock:
            if self._finished.is_set():
                return
            _shut_down_socket(self._connection)


def _shut_down_socket(connection: psycopg.Connection[Any]) -> None:
    try:
        # A duplicate, so that closing it here leaves the descriptor that libpq owns open.
        sock = socket.socket(fileno=os.dup(connection.fileno()))
    except Exception as e:
        logger.debug("data_imports.postgres_client_deadline_shutdown_failed", error=str(e)[:200])
        return
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError as e:
        logger.debug("data_imports.postgres_client_deadline_shutdown_failed", error=str(e)[:200])
    finally:
        sock.close()


@contextmanager
def client_side_deadline(
    connection: psycopg.Connection[Any], timeout_seconds: float, *, raise_deadline_error: bool = True
) -> Iterator[None]:
    """End the statement that runs inside the block when it takes longer than `timeout_seconds`.

    At the deadline the statement gets a cancel request. If it is still running
    `CANCEL_GRACE_SECONDS` later, the socket is shut down. The error that the statement then raises
    becomes a `ClientDeadlineExceededError`.

    With `raise_deadline_error=False` the statement keeps its own error: `QueryCanceled` after the
    cancel request, `OperationalError` after the shutdown.
    """
    watchdog = _StatementWatchdog(connection, timeout_seconds)
    watchdog.start()
    try:
        yield
    except Exception as e:
        if raise_deadline_error and watchdog.expired:
            raise ClientDeadlineExceededError(timeout_seconds) from e
        raise
    finally:
        watchdog.finish()


def deadline_cursor_factory(timeout_seconds: float) -> type[psycopg.Cursor[Any]]:
    """Return a cursor class that puts `client_side_deadline` on every `execute`."""

    class DeadlineCursor(psycopg.Cursor[Any]):
        def execute(
            self,
            query: Query,
            params: Params | None = None,
            *,
            prepare: bool | None = None,
            binary: bool | None = None,
        ) -> Self:
            with client_side_deadline(self.connection, timeout_seconds):
                return super().execute(query, params, prepare=prepare, binary=binary)

    return DeadlineCursor


def deadline_server_cursor_factory(timeout_seconds: float) -> type[psycopg.ServerCursor[Any]]:
    """Return a server cursor class that puts `client_side_deadline` on every round trip.

    Each `FETCH` is one round trip with its own deadline. The limit is thus on one silent wait
    and not on the read as a whole, so a long read that keeps returning rows never reaches it.
    """

    class DeadlineServerCursor(psycopg.ServerCursor[Any]):
        def execute(
            self,
            query: Query,
            params: Params | None = None,
            *,
            binary: bool | None = None,
            **kwargs: Any,
        ) -> Self:
            with client_side_deadline(self.connection, timeout_seconds):
                return super().execute(query, params, binary=binary, **kwargs)

        def fetchone(self) -> Any:
            with client_side_deadline(self.connection, timeout_seconds):
                return super().fetchone()

        def fetchmany(self, size: int = 0) -> list[Any]:
            with client_side_deadline(self.connection, timeout_seconds):
                return super().fetchmany(size)

        def fetchall(self) -> list[Any]:
            with client_side_deadline(self.connection, timeout_seconds):
                return super().fetchall()

        def close(self) -> None:
            # A close runs while the row generator unwinds, where the callers already handle the
            # native errors. A new error class here would hide the outcome of the read.
            with client_side_deadline(self.connection, timeout_seconds, raise_deadline_error=False):
                super().close()

    return DeadlineServerCursor
