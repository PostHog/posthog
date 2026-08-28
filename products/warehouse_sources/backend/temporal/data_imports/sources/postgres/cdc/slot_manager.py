"""Replication slot and publication lifecycle management for PostgreSQL CDC."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

import psycopg
from psycopg import sql

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

logger = logging.getLogger(__name__)


@contextmanager
def cdc_pg_connection(source: ExternalDataSource, connect_timeout: int = 15) -> Iterator[psycopg.Connection]:
    """Open a connection to the source database for CDC management operations.

    Handles SSH tunnel and delegates the actual connection
    to _connect_to_postgres which owns SSL cert overrides.
    """
    from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres import (
        _connect_to_postgres,
        source_requires_ssl,
    )
    from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.source import PostgresSource

    source_impl = PostgresSource()
    config = source_impl.parse_config(source.job_inputs or {})
    # Pass `config` so the SSH-tunnel `require_tls` opt-out is honored, matching the main
    # pipeline path. Without it SSL is forced on, and a database reached over an SSH tunnel
    # that doesn't speak SSL fails with "server does not support SSL, but SSL was required".
    require_ssl = source_requires_ssl(source, config)

    with source_impl.with_ssh_tunnel(config, source.team_id) as (host, port):
        conn = _connect_to_postgres(
            host=host,
            port=port,
            database=config.database,
            user=config.user,
            password=config.password,
            require_ssl=require_ssl,
            connect_timeout=connect_timeout,
        )
        try:
            yield conn
        finally:
            conn.close()


def create_slot_and_publication(
    conn: psycopg.Connection,
    slot_name: str,
    pub_name: str,
    tables: list[tuple[str, str]],
) -> str:
    """Create a publication and replication slot.

    ``tables`` is a list of ``(schema, table)`` pairs — each table is qualified by
    its own schema, since a publication can span schemas. An empty list creates an
    empty publication (tables added later via ALTER PUBLICATION ADD TABLE).

    Returns the consistent_point LSN from slot creation.
    """
    create_publication(conn, pub_name, tables)
    consistent_point = create_slot(conn, slot_name)
    logger.info("Created publication '%s' with slot '%s'", pub_name, slot_name)
    return consistent_point


def create_publication(
    conn: psycopg.Connection,
    pub_name: str,
    tables: list[tuple[str, str]],
) -> None:
    """Create a publication, optionally pre-populated with schema-qualified tables."""
    with conn.cursor() as cur:
        if tables:
            table_list = sql.SQL(", ").join(
                sql.SQL("{}.{}").format(sql.Identifier(table_schema), sql.Identifier(table_name))
                for table_schema, table_name in tables
            )
            cur.execute(
                sql.SQL("CREATE PUBLICATION {} FOR TABLE {} WITH (publish_via_partition_root = true)").format(
                    sql.Identifier(pub_name),
                    table_list,
                )
            )
        else:
            # Empty publication — tables added individually via ALTER PUBLICATION ADD TABLE
            cur.execute(
                sql.SQL("CREATE PUBLICATION {}").format(
                    sql.Identifier(pub_name),
                )
            )
        # Commit immediately so callers can create a replication slot on the same connection next.
        conn.commit()
    logger.info("Created publication '%s'", pub_name)


def create_slot(conn: psycopg.Connection, slot_name: str) -> str:
    """Create just a logical replication slot against an already-existing publication.

    Used by self-managed CDC: the customer's DBA creates the publication with an owner
    account, then PostHog creates and manages the slot with its own REPLICATION user.

    Returns the consistent_point LSN from slot creation.
    """
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("SELECT lsn FROM pg_create_logical_replication_slot({}, 'pgoutput')").format(
                sql.Literal(slot_name),
            )
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError(f"pg_create_logical_replication_slot returned no result for slot '{slot_name}'")
        consistent_point: str = row[0]
        conn.commit()

    logger.info("Created replication slot '%s' at LSN %s", slot_name, consistent_point)
    return consistent_point


def drop_slot(conn: psycopg.Connection, slot_name: str) -> None:
    """Drop just the replication slot. Best-effort — used by self-managed rollback,
    where the publication is customer-owned and must not be touched.
    """
    with conn.cursor() as cur:
        try:
            cur.execute(
                sql.SQL("SELECT pg_drop_replication_slot({})").format(sql.Literal(slot_name)),
            )
            conn.commit()
            logger.info("Dropped replication slot '%s'", slot_name)
        except psycopg.errors.UndefinedObject:
            conn.rollback()
            logger.info("Replication slot '%s' does not exist, skipping drop", slot_name)
        except Exception:
            conn.rollback()
            logger.exception("Failed to drop replication slot '%s'", slot_name)


def drop_slot_and_publication(
    conn: psycopg.Connection,
    slot_name: str,
    pub_name: str,
) -> None:
    """Drop a replication slot and publication. Best-effort — logs and continues on errors."""
    drop_slot(conn, slot_name)
    drop_publication(conn, pub_name)


def drop_publication(
    conn: psycopg.Connection,
    pub_name: str,
) -> None:
    """Drop a publication. Best-effort — logs and continues on errors."""
    with conn.cursor() as cur:
        try:
            cur.execute(
                sql.SQL("DROP PUBLICATION IF EXISTS {}").format(sql.Identifier(pub_name)),
            )
            conn.commit()
            logger.info("Dropped publication '%s'", pub_name)
        except Exception:
            conn.rollback()
            logger.exception("Failed to drop publication '%s'", pub_name)


def add_table_to_publication(
    conn: psycopg.Connection,
    pub_name: str,
    schema: str,
    table: str,
) -> None:
    """Add a table to an existing publication. No-op if already a member."""
    with conn.cursor() as cur:
        try:
            cur.execute(
                sql.SQL("ALTER PUBLICATION {} ADD TABLE {}.{}").format(
                    sql.Identifier(pub_name),
                    sql.Identifier(schema),
                    sql.Identifier(table),
                )
            )
            conn.commit()
        except psycopg.errors.DuplicateObject:
            conn.rollback()
            logger.info("Table %s.%s is already in publication '%s', skipping", schema, table, pub_name)
            return

    logger.info("Added table %s.%s to publication '%s'", schema, table, pub_name)


def remove_table_from_publication(
    conn: psycopg.Connection,
    pub_name: str,
    schema: str,
    table: str,
) -> None:
    """Remove a table from an existing publication. No-op if not a member."""
    with conn.cursor() as cur:
        try:
            cur.execute(
                sql.SQL("ALTER PUBLICATION {} DROP TABLE {}.{}").format(
                    sql.Identifier(pub_name),
                    sql.Identifier(schema),
                    sql.Identifier(table),
                )
            )
            conn.commit()
        except psycopg.errors.UndefinedTable:
            conn.rollback()
            logger.info("Table %s.%s is not in publication '%s', skipping", schema, table, pub_name)
            return

    logger.info("Removed table %s.%s from publication '%s'", schema, table, pub_name)


# Substrings of the errors Postgres raises when reading from / advancing a slot that it
# invalidated (max_slot_wal_keep_size exceeded). Wordings differ across PG 13–17.
_SLOT_INVALIDATION_MESSAGE_MARKERS = (
    "can no longer get changes from replication slot",
    "slot has been invalidated",
    "cannot advance replication slot that has not previously reserved WAL",
)


def is_slot_invalidation_error(exc: BaseException) -> bool:
    """Whether the exception (or anything in its chain) means the replication slot is
    unusable and must be recreated: invalidated by Postgres or dropped entirely.
    """
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        message = str(current)
        if isinstance(current, psycopg.errors.ObjectNotInPrerequisiteState) and any(
            marker in message for marker in _SLOT_INVALIDATION_MESSAGE_MARKERS
        ):
            return True
        if (
            isinstance(current, psycopg.errors.UndefinedObject)
            and "replication slot" in message
            and "does not exist" in message
        ):
            return True
        current = current.__cause__ or current.__context__
    return False


def get_max_slot_wal_keep_size_mb(conn: psycopg.Connection) -> int | None:
    """The server's max_slot_wal_keep_size in MB, or None when unlimited (-1) or unreadable."""
    with conn.cursor() as cur:
        cur.execute("SELECT setting::bigint FROM pg_settings WHERE name = 'max_slot_wal_keep_size'")
        row = cur.fetchone()
    if row is None or row[0] is None:
        return None
    value = int(row[0])
    return value if value >= 0 else None


def get_slot_lag_bytes(conn: psycopg.Connection, slot_name: str) -> int | None:
    """Get the WAL lag in bytes for a replication slot.

    Returns None if the slot doesn't exist or has no confirmed_flush_lsn.
    """
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                "SELECT pg_wal_lsn_diff(pg_current_wal_lsn(), confirmed_flush_lsn)::bigint "
                "FROM pg_replication_slots WHERE slot_name = {}"
            ).format(sql.Literal(slot_name))
        )
        row = cur.fetchone()
        if row is None or row[0] is None:
            return None
        return int(row[0])


def slot_exists(conn: psycopg.Connection, slot_name: str) -> bool:
    """Check if a replication slot exists."""
    with conn.cursor() as cur:
        cur.execute(sql.SQL("SELECT 1 FROM pg_replication_slots WHERE slot_name = {}").format(sql.Literal(slot_name)))
        return cur.fetchone() is not None


def publication_exists(conn: psycopg.Connection, pub_name: str) -> bool:
    """Check if a publication exists."""
    with conn.cursor() as cur:
        cur.execute(sql.SQL("SELECT 1 FROM pg_publication WHERE pubname = {}").format(sql.Literal(pub_name)))
        return cur.fetchone() is not None


def get_publication_tables(conn: psycopg.Connection, pub_name: str) -> list[str]:
    """List the schema-qualified tables (``schema.table``) in a publication, sorted.

    Returns an empty list when the publication doesn't exist or has no tables.
    These are exactly the tables whose changes the replication slot streams.
    """
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                "SELECT schemaname, tablename FROM pg_publication_tables "
                "WHERE pubname = {} ORDER BY schemaname, tablename"
            ).format(sql.Literal(pub_name))
        )
        return [f"{schemaname}.{tablename}" for schemaname, tablename in cur.fetchall()]
