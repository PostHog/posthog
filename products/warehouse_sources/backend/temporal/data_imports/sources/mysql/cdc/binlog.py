"""Reads of a MySQL server's binary log state, over a management connection."""

from __future__ import annotations

import time
import random
import threading
from typing import Any

import pymysql

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc.position import (
    BinlogPosition,
    BinlogStreamOutgrownError,
)

# ER_MASTER_FATAL_ERROR_READING_BINLOG: the server can't serve the requested position, most often because
# the file was purged.
ER_BINLOG_UNAVAILABLE = 1236
# A replica id is a 32-bit unsigned number. Stay above the low ids DBAs hand out to their own replicas.
_SERVER_ID_RANGE = (1 << 24, (1 << 32) - 1)
_VISIBILITY_TIMEOUT_SECONDS = 60.0
# Further apart than the 0.1 s INNODB_TRX needs to go unread before it refreshes its cache.
_VISIBILITY_POLL_SECONDS = 0.2


class BinlogStreamLostError(Exception):
    """The binlog can no longer be read from PostHog's position: the file was purged, or the source now points
    at another server. Capture recovers by starting a new stream and re-snapshotting."""


class BinlogPositionNotVisibleError(Exception):
    """Transactions that were committing when the position was read did not finish in time."""


@frozen
class BinlogFile:
    name: str
    size: int


def binlog_status(conn: pymysql.Connection) -> tuple[str, int]:
    """The file and offset the server writes its next event to."""
    with conn.cursor() as cur:
        try:
            cur.execute("SHOW BINARY LOG STATUS")
        except pymysql.err.ProgrammingError:
            # Before 8.2 the statement has its old name.
            cur.execute("SHOW MASTER STATUS")
        row = cur.fetchone()
    if row is None:
        raise BinlogStreamLostError("Binary logging is off on the source database")
    return str(row[0]), int(row[1])


def binary_logs(conn: pymysql.Connection) -> list[BinlogFile]:
    with conn.cursor() as cur:
        cur.execute("SHOW BINARY LOGS")
        return [BinlogFile(name=str(row[0]), size=int(row[1])) for row in cur.fetchall()]


def server_uuid(conn: pymysql.Connection) -> str:
    with conn.cursor() as cur:
        cur.execute("SELECT @@GLOBAL.server_uuid")
        row = cur.fetchone()
    return str(row[0]) if row else ""


def visible_position(conn: pymysql.Connection, epoch: int, base: int | None = None) -> BinlogPosition:
    """The end of the binlog, once every change at or below it is visible to a new read.

    MySQL writes a transaction to the binlog before InnoDB commits it, so a transaction can sit below the
    end of the binlog and still be invisible. Every such transaction is open when the position is read, so
    waiting for the writing transactions open then to end closes the gap. Reading them needs PROCESS.
    ``base`` is the first file of the stream the position belongs to, None for a new stream.
    """
    deadline = time.monotonic() + _VISIBILITY_TIMEOUT_SECONDS
    file, offset = binlog_status(conn)
    open_ids = _writing_transactions(conn, deadline)
    while open_ids:
        placeholders = ", ".join(["%s"] * len(open_ids))
        with conn.cursor() as cur:
            cur.execute(f"SELECT trx_id FROM information_schema.INNODB_TRX WHERE trx_id IN ({placeholders})", open_ids)
            # A cached list can only hold transactions that have since ended, which costs a poll, not a change.
            open_ids = [row[0] for row in cur.fetchall()]
        if not open_ids:
            break
        _wait_or_raise(deadline, f"{len(open_ids)} transactions stayed open past the position")
    return BinlogPosition.at(epoch, file, offset, base=base)


def _writing_transactions(conn: pymysql.Connection, deadline: float) -> list[Any]:
    """Ids of the InnoDB transactions that have written rows, from a list taken after this call started.

    INNODB_TRX serves a cache that refreshes only once it has gone unread for 0.1 s, so another session that
    reads it often can keep serving a list from before the position was read. A snapshot transaction opened
    here proves the list is newer once the list contains it.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT CONNECTION_ID()")
        (own_thread,) = cur.fetchone()
        cur.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT")
        try:
            while True:
                cur.execute("SELECT trx_id, trx_mysql_thread_id, trx_rows_modified FROM information_schema.INNODB_TRX")
                rows = cur.fetchall()
                if any(thread == own_thread for _, thread, _ in rows):
                    # A transaction that changed no row writes nothing to the binlog, so a long read can't hold
                    # this up.
                    return [trx_id for trx_id, thread, modified in rows if thread != own_thread and modified > 0]
                _wait_or_raise(deadline, "The server kept serving a cached transaction list")
        finally:
            cur.execute("COMMIT")


def _wait_or_raise(deadline: float, reason: str) -> None:
    if time.monotonic() >= deadline:
        raise BinlogPositionNotVisibleError(reason)
    threading.Event().wait(_VISIBILITY_POLL_SECONDS)


def require_readable(conn: pymysql.Connection, position: BinlogPosition, expected_server_uuid: str) -> None:
    """Raise ``BinlogStreamLostError`` when the server can't continue the stream from ``position``."""
    current_uuid = server_uuid(conn)
    if expected_server_uuid and current_uuid != expected_server_uuid:
        raise BinlogStreamLostError(
            f"The source now points at another MySQL server (server_uuid {current_uuid}, "
            f"expected {expected_server_uuid}), so the binlog position no longer applies"
        )
    names = {file.name for file in binary_logs(conn)}
    if position.file not in names:
        raise BinlogStreamLostError(f"The binlog file {position.file} was purged before PostHog read it")


def lag_bytes(conn: pymysql.Connection, position: BinlogPosition) -> int | None:
    """Binlog bytes written after ``position``, or None when its file is gone."""
    files = binary_logs(conn)
    behind = 0
    found = False
    for file in files:
        if file.name == position.file:
            found = True
            behind += max(file.size - position.offset, 0)
        elif found:
            behind += file.size
    return behind if found else None


def unused_server_id(conn: pymysql.Connection) -> int:
    """A replica id no registered replica of the server uses."""
    with conn.cursor() as cur:
        try:
            cur.execute("SHOW REPLICAS")
        except pymysql.err.ProgrammingError:
            cur.execute("SHOW SLAVE HOSTS")
        taken = {int(row[0]) for row in cur.fetchall()}
        cur.execute("SELECT @@GLOBAL.server_id")
        row = cur.fetchone()
    if row:
        taken.add(int(row[0]))
    while True:
        candidate = random.randint(*_SERVER_ID_RANGE)
        if candidate not in taken:
            return candidate


def is_stream_lost_error(exc: BaseException) -> bool:
    if isinstance(exc, BinlogStreamLostError | BinlogStreamOutgrownError):
        return True
    return isinstance(exc, pymysql.err.OperationalError) and bool(exc.args) and exc.args[0] == ER_BINLOG_UNAVAILABLE
