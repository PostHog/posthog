"""SQL-based CDC stream reader for PostgreSQL.

Uses pg_logical_slot_peek_binary_changes() to read WAL changes via a regular
SQL connection (not the streaming replication protocol). This is the Option E
approach — batch reads on a schedule.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import TYPE_CHECKING

import psycopg
import structlog
import psycopg.errors
from psycopg import sql

from products.warehouse_sources.backend.temporal.data_imports.cdc.types import ChangeEvent
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.decoder import PgOutputDecoder
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres import (
    _connect_to_postgres,
    _connect_with_dropped_retry,
    get_primary_key_columns,
)

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

logger = structlog.get_logger(__name__)

# pg_replication_slot_advance rejects the advance with SQLSTATE 55006 (ObjectInUse) while the slot
# is still acquired by another backend. The advance runs on its own short-lived connection while the
# streaming peek releases the slot, so the two can momentarily overlap; the slot frees on its own.
_SLOT_ACTIVE_MARKER = "is active for pid"
_SLOT_ADVANCE_MAX_ATTEMPTS = 3

# The first fetch of pg_logical_slot_peek_binary_changes acquires the replication slot, which
# Postgres rejects with SQLSTATE 55006 (ObjectInUse, "... is active for PID ...") while a prior
# run's connection is still releasing it. The slot frees on its own, so a short in-process retry
# absorbs the handoff instead of failing — and replaying — the whole extraction attempt.
_SLOT_READ_MAX_ATTEMPTS = 4


@dataclass(frozen=True, slots=True)
class PgCDCConnectionParams:
    host: str
    port: int
    database: str
    user: str
    password: str
    require_ssl: bool = False
    slot_name: str = ""
    publication_name: str = ""


class PgCDCStreamReader:
    """Reads WAL changes from a PostgreSQL replication slot using SQL queries.

    Uses pg_logical_slot_peek_binary_changes() for non-destructive reads
    and pg_replication_slot_advance() for explicit position confirmation.

    SSH tunneling: when ``source`` is provided, ``connect()`` opens an SSH tunnel
    via ``PostgresSource.with_ssh_tunnel`` and rewrites the connection host/port to
    the local tunnel endpoint. The tunnel stays open until ``close()`` is called,
    so both the streaming cursor and short-lived ``confirm_position`` connections
    use the same tunnel.
    """

    def __init__(self, params: PgCDCConnectionParams, source: ExternalDataSource | None = None) -> None:
        self._params = params
        self._source = source
        self._conn: psycopg.Connection | None = None
        self._decoder = PgOutputDecoder()
        self._tunnel_cm: AbstractContextManager[tuple[str, int]] | None = None
        self._effective_host: str = params.host
        self._effective_port: int = params.port
        self._last_rows_consumed: int = 0

    def connect(self) -> None:
        # If a source is provided, enter the SSH tunnel context (no-op if SSH is disabled).
        # The tunnel must stay open for the lifetime of the reader so confirm_position
        # connections can also reach the source DB.
        if self._source is not None:
            from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source import PostgresSource

            source_impl = PostgresSource()
            config = source_impl.parse_config(self._source.job_inputs or {})
            tunnel_cm = source_impl.with_ssh_tunnel(config, self._source.team_id)
            self._effective_host, self._effective_port = tunnel_cm.__enter__()
            self._tunnel_cm = tunnel_cm

        # The initial connect reaches the source through the just-opened SSH tunnel /
        # connection pooler, either of which can drop the first connection with a
        # transient "server closed the connection unexpectedly". Mirror the non-CDC
        # read paths and absorb those drops in-process instead of failing the whole
        # extraction activity; permanent errors (auth, SSL-required) are re-raised
        # immediately by the helper.
        self._conn = _connect_with_dropped_retry(
            lambda: _connect_to_postgres(
                host=self._effective_host,
                port=self._effective_port,
                database=self._params.database,
                user=self._params.user,
                password=self._params.password,
                require_ssl=self._params.require_ssl,
                # statement_timeout (30m) is a server-side ceiling so a stalled WAL decode can't
                # hang the streaming connection indefinitely; it bounds a single peek, the caller's
                # soft deadline bounds the whole run. idle_in_transaction_session_timeout=0 stops the
                # source culling our backend (SQLSTATE 25P03) while the named cursor's transaction
                # sits idle between yields as the caller flushes to S3 and advances the slot —
                # statement_timeout doesn't apply there because no statement is running. Both are
                # dropped if the source sits behind a pooler that rejects the libpq `options`
                # parameter (CDC sources never do).
                options="-c statement_timeout=1800000 -c idle_in_transaction_session_timeout=0",
            ),
            logger,
        )

    def read_changes(
        self,
        upto_nchanges: int | None = None,
        on_row: Callable[[], None] | None = None,
    ) -> Iterator[ChangeEvent]:
        """Read pending WAL changes from the replication slot.

        Uses peek (non-consuming) so the slot position is not advanced.
        Call confirm_position() after successful processing.

        ``upto_nchanges`` bounds one peek: ``pg_logical_slot_peek_binary_changes`` stops once a
        transaction's COMMIT pushes the decoded-change count past it. It never splits a
        transaction, so a single large transaction is still returned in full (the decoder's own
        buffer guard bounds that case). ``None`` reads the whole backlog.

        ``on_row`` is invoked once per fetched WAL row so the caller can heartbeat during a long
        decode — the decoder yields nothing until a COMMIT, so a big transaction would otherwise
        produce no events to drive a heartbeat off.

        After iteration, ``last_rows_consumed`` holds the raw row count for this call so the
        caller can detect a full page (rows reached the cap) and peek again.

        Uses a named server-side cursor to stream rows in chunks rather than
        buffering the entire WAL backlog in client memory.
        """
        if self._conn is None:
            raise RuntimeError("Not connected. Call connect() first.")
        conn = self._conn

        self._last_rows_consumed = 0
        upto = sql.Literal(upto_nchanges) if upto_nchanges is not None else sql.SQL("NULL")
        query = sql.SQL(
            "SELECT lsn, xid, data FROM pg_logical_slot_peek_binary_changes("
            "{slot_name}, NULL, {upto_nchanges}, "
            "'proto_version', '1', "
            "'publication_names', {pub_name}"
            ")"
        ).format(
            slot_name=sql.Literal(self._params.slot_name),
            upto_nchanges=upto,
            pub_name=sql.Literal(self._params.publication_name),
        )

        # The named cursor runs the peek lazily, so the slot is acquired on the first fetch — that
        # is where "... is active for PID ..." surfaces, before any event is yielded. Retry that
        # handoff in-process so a prior run's still-releasing connection can't fail the whole
        # attempt. Once a row lands the slot is ours, so never retry past that point; if it stays
        # held the error propagates to the retryable SLOT_IN_USE path.
        for attempt in range(_SLOT_READ_MAX_ATTEMPTS):
            slot_acquired = False
            try:
                with conn.cursor(name="cdc_stream") as cur:
                    cur.itersize = 1000
                    cur.execute(query)

                    for row in cur:
                        slot_acquired = True
                        self._last_rows_consumed += 1
                        if on_row is not None:
                            on_row()

                        lsn_str: str = row[0]
                        data: bytes = row[2]

                        events = self._decoder.decode_message(data, lsn_str)
                        yield from events
                return
            except psycopg.errors.ObjectInUse as e:
                conn.rollback()
                if slot_acquired or _SLOT_ACTIVE_MARKER not in str(e).lower() or attempt == _SLOT_READ_MAX_ATTEMPTS - 1:
                    raise
                self._last_rows_consumed = 0
                logger.warning("slot_read_busy_retry", slot_name=self._params.slot_name, attempt=attempt + 1)
                time.sleep(0.5 * 2**attempt)

    def confirm_position(self, position: str) -> None:
        """Advance the replication slot to the given LSN.

        This consumes all WAL up to and including the given position.
        Safe to call mid-iteration of ``read_changes()`` because it opens its own
        short-lived connection rather than reusing the streaming cursor's connection
        (which can't run other queries while the named server-side cursor is active).
        """
        query = sql.SQL("SELECT pg_replication_slot_advance({slot_name}, {lsn})").format(
            slot_name=sql.Literal(self._params.slot_name),
            lsn=sql.Literal(position),
        )

        # This short-lived connection reaches the source through the same SSH tunnel /
        # connection pooler as the initial connect, either of which can drop it with a
        # transient "server closed the connection unexpectedly". Mirror connect() and
        # absorb those drops in-process rather than failing the whole extraction
        # activity; permanent errors (auth, SSL-required) are re-raised immediately.
        advance_conn = _connect_with_dropped_retry(
            lambda: _connect_to_postgres(
                host=self._effective_host,
                port=self._effective_port,
                database=self._params.database,
                user=self._params.user,
                password=self._params.password,
                require_ssl=self._params.require_ssl,
            ),
            logger,
        )
        try:
            self._advance_slot(advance_conn, query)
        finally:
            advance_conn.close()

        logger.info("advanced_slot", slot_name=self._params.slot_name, position=position)

    def _advance_slot(self, conn: psycopg.Connection, query: sql.Composed) -> None:
        """Run the slot-advance query, retrying the brief window where the slot is still
        held by another backend ("... is active for PID ...").

        Advancing is idempotent (re-advancing past a confirmed LSN is a no-op), and the slot
        frees on its own, so a short in-process retry absorbs a sub-second handoff instead of
        failing — and replaying — the whole extraction. Exhausting the retries re-raises, so a
        slot that stays held still surfaces as the retryable SLOT_IN_USE classification.
        """
        for attempt in range(_SLOT_ADVANCE_MAX_ATTEMPTS):
            try:
                with conn.cursor() as cur:
                    cur.execute(query)
                conn.commit()
                return
            except psycopg.errors.ObjectInUse as e:
                conn.rollback()
                if _SLOT_ACTIVE_MARKER not in str(e).lower() or attempt == _SLOT_ADVANCE_MAX_ATTEMPTS - 1:
                    raise
                logger.warning("slot_advance_busy_retry", slot_name=self._params.slot_name, attempt=attempt + 1)
                time.sleep(0.5 * 2**attempt)

    def get_primary_key_columns(self, schema_name: str, table_names: list[str]) -> dict[str, list[str]]:
        """Query information_schema for PK columns of the given tables.

        Returns a dict of table_name → list of PK column names.
        """
        if self._conn is None:
            raise RuntimeError("Not connected. Call connect() first.")
        return get_primary_key_columns(self._conn, schema_name, table_names)

    @property
    def truncated_tables(self) -> list[str]:
        """Tables that received a TRUNCATE during the last read_changes() call."""
        return self._decoder.truncated_tables

    def clear_truncated_tables(self) -> None:
        self._decoder.clear_truncated_tables()

    def get_decoder_key_columns(self, table_name: str) -> list[str]:
        """Return PK columns discovered by the decoder from Relation messages during read_changes()."""
        return self._decoder.get_key_columns(table_name)

    @property
    def last_commit_end_lsn(self) -> str | None:
        """End LSN of the most recently committed transaction.

        Non-None even when only TRUNCATE messages were decoded (no ChangeEvents).
        Use this to advance the slot when event_count == 0 but truncates occurred.
        """
        return self._decoder.last_commit_end_lsn

    @property
    def last_rows_consumed(self) -> int:
        """Raw WAL rows fetched during the most recent ``read_changes()`` call.

        Reaches the ``upto_nchanges`` cap (or slightly above it, since a transaction is never
        split) while the slot still has a backlog; stays below it once the backlog is drained.
        """
        return self._last_rows_consumed

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
        if self._tunnel_cm is not None:
            self._tunnel_cm.__exit__(None, None, None)
            self._tunnel_cm = None
