"""Reads of a MySQL server's binary log state, over a management connection."""

from __future__ import annotations

import time
import random
import threading

import pymysql

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.mysql.cdc.position import BinlogPosition

# ER_MASTER_FATAL_ERROR_READING_BINLOG: the server can't serve the requested position, most often because
# the file was purged.
ER_BINLOG_UNAVAILABLE = 1236
# A replica id is a 32-bit unsigned number. Stay above the low ids DBAs hand out to their own replicas.
_SERVER_ID_RANGE = (1 << 24, (1 << 32) - 1)
_VISIBILITY_TIMEOUT_SECONDS = 60.0
# INNODB_TRX serves a cache that refreshes only once it has gone unread for 0.1 s, so polls must be further apart.
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


def visible_position(conn: pymysql.Connection, epoch: int) -> BinlogPosition:
    """The end of the binlog, once every change at or below it is visible to a new read.

    MySQL writes a transaction to the binlog before InnoDB commits it, so a transaction can sit below the
    end of the binlog and still be invisible. Every such transaction is open when the position is read, so
    waiting for the writing transactions open then to end closes the gap. Reading them needs PROCESS.
    """
    file, offset = binlog_status(conn)
    with conn.cursor() as cur:
        # A transaction that changed no row writes nothing to the binlog, so a long read can't hold this up.
        cur.execute("SELECT trx_id FROM information_schema.INNODB_TRX WHERE trx_rows_modified > 0")
        open_ids = [row[0] for row in cur.fetchall()]
    deadline = time.monotonic() + _VISIBILITY_TIMEOUT_SECONDS
    while open_ids:
        placeholders = ", ".join(["%s"] * len(open_ids))
        with conn.cursor() as cur:
            cur.execute(f"SELECT trx_id FROM information_schema.INNODB_TRX WHERE trx_id IN ({placeholders})", open_ids)
            open_ids = [row[0] for row in cur.fetchall()]
        if not open_ids:
            break
        if time.monotonic() >= deadline:
            raise BinlogPositionNotVisibleError(f"{len(open_ids)} transactions stayed open past the position")
        threading.Event().wait(_VISIBILITY_POLL_SECONDS)
    return BinlogPosition.at(epoch, file, offset)


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
    if isinstance(exc, BinlogStreamLostError):
        return True
    return isinstance(exc, pymysql.err.OperationalError) and bool(exc.args) and exc.args[0] == ER_BINLOG_UNAVAILABLE
