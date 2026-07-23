"""Postgres statistics catalogs for the opt-in database-statistics schemas.

Each catalog is snapshotted as the server exposes it — ``SELECT *`` plus the snapshot
identity, and, where Postgres only offers a value as a function call (relation sizes,
index definitions, slot lag), one clearly-named computed column. No renaming, no
reshaping, no dropped columns: ``pg_stat_user_tables`` in the warehouse has the columns
a DBA expects from ``pg_stat_user_tables``.

Every catalog degrades independently: one the credentials can't read appends an empty
snapshot with a warning rather than failing the sync, so a plain read-only user still
gets everything Postgres exposes to PUBLIC.
"""

from collections.abc import Callable, Iterator, Mapping
from contextlib import _GeneratorContextManager, contextmanager
from datetime import datetime
from functools import partial
from typing import Any, Protocol

import psycopg
from psycopg import sql
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.database_stats import (
    DatabaseStatsCatalog,
    build_database_stats_source_response,
    snapshot_rows,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres import (
    _normalize_selected_schema,
    pg_connection,
)

# Row caps per snapshot. Statements are ranked by cumulative execution time and tables
# and indexes by size, so the cap keeps the rows that matter.
STATEMENTS_SNAPSHOT_LIMIT = 500
TABLES_SNAPSHOT_LIMIT = 5_000
INDEXES_SNAPSHOT_LIMIT = 10_000

# Restricts the table and index catalogs to the schema the source imports from. Applied
# only when the source is scoped to one schema; `pg_stat_statements` carries no schema
# attribution to filter on — see `_collect_statements`.
_SCHEMA_PREDICATE = sql.SQL("WHERE s.schemaname = {schema}")


class _PostgresStatsCollector(Protocol):
    """A Postgres collector: the generic contract plus this engine's schema scope."""

    def __call__(
        self,
        conn: psycopg.Connection,
        logger: FilteringBoundLogger,
        collected_at: datetime,
        snapshot_id: str,
        source_schema: str | None = None,
    ) -> list[dict[str, Any]]: ...


def _scope_predicate(source_schema: str | None) -> sql.SQL | sql.Composed:
    if not source_schema:
        return sql.SQL("")
    return _SCHEMA_PREDICATE.format(schema=sql.Literal(source_schema))


def _pg_stat_statements_relation(cur: psycopg.Cursor) -> sql.Identifier | None:
    """The qualified pg_stat_statements view, or None when the extension isn't installed.

    Resolved through pg_extension because the extension can live outside the search_path
    (e.g. a dedicated `extensions` schema on Supabase).
    """
    cur.execute(
        """
        SELECT n.nspname
        FROM pg_extension e
        JOIN pg_namespace n ON n.oid = e.extnamespace
        WHERE e.extname = 'pg_stat_statements'
        """
    )
    row = cur.fetchone()
    if row is None:
        return None
    return sql.Identifier(row[0], "pg_stat_statements")


def _collect_statements(
    conn: psycopg.Connection,
    logger: FilteringBoundLogger,
    collected_at: datetime,
    snapshot_id: str,
    source_schema: str | None = None,
) -> list[dict[str, Any]]:
    """Snapshot per-statement stats for the connected database.

    Scoped to the current `dbid`: pg_stat_statements is cluster-wide (one row per
    userid/dbid/queryid), so other databases' query text must never land in this team's
    warehouse, and an unscoped top-N would spend its budget on their traffic.

    Not scoped by schema: pg_stat_statements records no schema for a statement — one
    entry can touch several schemas, or none resolvable without parsing SQL against the
    server's `search_path`. Omitting unattributable rows would empty the table rather
    than scope it, so on a schema-restricted source the normalized text here can mention
    objects in other schemas of the same database.
    """
    with conn.cursor() as cur:
        relation = _pg_stat_statements_relation(cur)
        if relation is None:
            logger.info("database_stats: pg_stat_statements is not installed, snapshot will be empty")
            return []

        # `total_exec_time` was `total_time` before pg_stat_statements 1.8; order by
        # whichever this server has so the row cap keeps the most expensive statements.
        for order_column in ("total_exec_time", "total_time"):
            try:
                cur.execute(
                    sql.SQL(
                        """
                        SELECT * FROM {relation}
                        WHERE dbid = (SELECT oid FROM pg_database WHERE datname = current_database())
                        ORDER BY {order_column} DESC
                        LIMIT {limit}
                        """
                    ).format(
                        relation=relation,
                        order_column=sql.Identifier(order_column),
                        limit=sql.Literal(STATEMENTS_SNAPSHOT_LIMIT),
                    )
                )
                break
            except psycopg.errors.UndefinedColumn:
                continue
        else:
            logger.warning("database_stats: pg_stat_statements has an unexpected column set, skipping")
            return []

        return snapshot_rows(cur, collected_at, snapshot_id)


def _collect_tables(
    conn: psycopg.Connection,
    logger: FilteringBoundLogger,
    collected_at: datetime,
    snapshot_id: str,
    source_schema: str | None = None,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                """
                SELECT s.*, pg_total_relation_size(s.relid) AS total_size_bytes
                FROM pg_stat_user_tables s
                {scope}
                ORDER BY pg_total_relation_size(s.relid) DESC
                LIMIT {limit}
                """
            ).format(scope=_scope_predicate(source_schema), limit=sql.Literal(TABLES_SNAPSHOT_LIMIT))
        )
        return snapshot_rows(cur, collected_at, snapshot_id)


def _collect_indexes(
    conn: psycopg.Connection,
    logger: FilteringBoundLogger,
    collected_at: datetime,
    snapshot_id: str,
    source_schema: str | None = None,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                """
                SELECT s.*,
                       pg_relation_size(s.indexrelid) AS index_size_bytes,
                       pg_get_indexdef(s.indexrelid) AS index_definition
                FROM pg_stat_user_indexes s
                {scope}
                ORDER BY pg_relation_size(s.indexrelid) DESC
                LIMIT {limit}
                """
            ).format(scope=_scope_predicate(source_schema), limit=sql.Literal(INDEXES_SNAPSHOT_LIMIT))
        )
        return snapshot_rows(cur, collected_at, snapshot_id)


def _collect_statio_tables(
    conn: psycopg.Connection,
    logger: FilteringBoundLogger,
    collected_at: datetime,
    snapshot_id: str,
    source_schema: str | None = None,
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL(
                """
                SELECT s.* FROM pg_statio_user_tables s
                {scope}
                LIMIT {limit}
                """
            ).format(scope=_scope_predicate(source_schema), limit=sql.Literal(TABLES_SNAPSHOT_LIMIT))
        )
        return snapshot_rows(cur, collected_at, snapshot_id)


def _collect_database(
    conn: psycopg.Connection,
    logger: FilteringBoundLogger,
    collected_at: datetime,
    snapshot_id: str,
    source_schema: str | None = None,
) -> list[dict[str, Any]]:
    """Database-wide counters — one row, for the connected database only."""
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM pg_stat_database WHERE datname = current_database()")
        return snapshot_rows(cur, collected_at, snapshot_id)


def _collect_settings(
    conn: psycopg.Connection,
    logger: FilteringBoundLogger,
    collected_at: datetime,
    snapshot_id: str,
    source_schema: str | None = None,
) -> list[dict[str, Any]]:
    """Server configuration. Cluster-wide by nature — settings aren't per-schema."""
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM pg_settings")
        return snapshot_rows(cur, collected_at, snapshot_id)


def _collect_replication_slots(
    conn: psycopg.Connection,
    logger: FilteringBoundLogger,
    collected_at: datetime,
    snapshot_id: str,
    source_schema: str | None = None,
) -> list[dict[str, Any]]:
    """Replication slots for the connected database, with retained-WAL lag.

    Slots are a cluster-wide catalog, so scope to the connected database: another
    database's slot names and lag must not land here. Logical slots (including our own
    CDC slots, the reason this is collected) carry `database`; physical slots have it
    NULL and belong to no database, so the same filter excludes them.

    `pg_current_wal_lsn()` errors on a standby, so lag is only computed on a primary.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT pg_is_in_recovery()")
        row = cur.fetchone()
        in_recovery = bool(row[0]) if row else False

        lag = (
            sql.SQL("NULL::bigint")
            if in_recovery
            else sql.SQL("pg_wal_lsn_diff(pg_current_wal_lsn(), s.restart_lsn)::bigint")
        )
        cur.execute(
            sql.SQL(
                """
                SELECT s.*, {lag} AS retained_wal_bytes
                FROM pg_replication_slots s
                WHERE s.database = current_database()
                """
            ).format(lag=lag)
        )
        return snapshot_rows(cur, collected_at, snapshot_id)


def _collect_activity_summary(
    conn: psycopg.Connection,
    logger: FilteringBoundLogger,
    collected_at: datetime,
    snapshot_id: str,
    source_schema: str | None = None,
) -> list[dict[str, Any]]:
    """Backend counts by state — deliberately an aggregate, not a mirror.

    Raw `pg_stat_activity` is a point-in-time list of live sessions carrying client
    addresses, usernames and (for the connecting role's own backends) query text. The
    signal wanted here is connection saturation, which a count answers, so this stays
    aggregated. Cluster-wide on purpose: `max_connections` is a cluster-wide limit, so
    only a cluster-wide count answers "how close is this server to saturation?", and
    counts by state reveal nothing about what other databases are running.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT coalesce(state, 'unknown') AS state,
                   count(*)::bigint AS backends,
                   count(*) FILTER (WHERE datname = current_database())::bigint AS backends_current_database
            FROM pg_stat_activity
            GROUP BY 1
            """
        )
        return snapshot_rows(cur, collected_at, snapshot_id)


POSTGRES_STATS_CATALOGS: dict[str, DatabaseStatsCatalog] = {
    catalog.table_name: catalog
    for catalog in (
        DatabaseStatsCatalog(
            table_name="pg_stat_statements",
            description=(
                "Snapshots of pg_stat_statements for this database: per-statement call counts, "
                "execution time, rows and block I/O. Counters are cumulative since the last "
                "statistics reset. Requires the pg_stat_statements extension."
            ),
            collector=_collect_statements,
            catalog_relation="pg_stat_statements",
        ),
        DatabaseStatsCatalog(
            table_name="pg_stat_user_tables",
            description=(
                "Snapshots of pg_stat_user_tables: sequential and index scans, live and dead "
                "rows, and vacuum/analyze timestamps, plus total_size_bytes."
            ),
            collector=_collect_tables,
            catalog_relation="pg_stat_user_tables",
            computed_columns=(("total_size_bytes", "bigint", True),),
        ),
        DatabaseStatsCatalog(
            table_name="pg_stat_user_indexes",
            description=(
                "Snapshots of pg_stat_user_indexes: per-index scan counts, plus index_size_bytes and index_definition."
            ),
            collector=_collect_indexes,
            catalog_relation="pg_stat_user_indexes",
            computed_columns=(
                ("index_size_bytes", "bigint", True),
                ("index_definition", "text", True),
            ),
        ),
        DatabaseStatsCatalog(
            table_name="pg_statio_user_tables",
            description="Snapshots of pg_statio_user_tables: per-table buffer cache hits and disk reads.",
            collector=_collect_statio_tables,
            catalog_relation="pg_statio_user_tables",
        ),
        DatabaseStatsCatalog(
            table_name="pg_stat_database",
            description=(
                "Snapshots of pg_stat_database for this database: commits, rollbacks, cache hits, "
                "deadlocks, temp files and conflicts."
            ),
            collector=_collect_database,
            catalog_relation="pg_stat_database",
        ),
        DatabaseStatsCatalog(
            table_name="pg_settings",
            description="Snapshots of pg_settings: the server's configuration parameters and their sources.",
            collector=_collect_settings,
            catalog_relation="pg_settings",
        ),
        DatabaseStatsCatalog(
            table_name="pg_replication_slots",
            description=(
                "Snapshots of pg_replication_slots for this database, plus retained_wal_bytes "
                "(NULL on a standby, where it can't be measured)."
            ),
            collector=_collect_replication_slots,
            catalog_relation="pg_replication_slots",
            computed_columns=(("retained_wal_bytes", "bigint", True),),
        ),
        DatabaseStatsCatalog(
            table_name="pg_stat_activity_summary",
            description=(
                "Backend counts by state, cluster-wide and for this database. An aggregate of "
                "pg_stat_activity rather than a copy, so no session details are collected."
            ),
            collector=_collect_activity_summary,
            static_columns=(
                ("state", "text", True),
                ("backends", "bigint", True),
                ("backends_current_database", "bigint", True),
            ),
        ),
    )
}


def fetch_postgres_stats_columns(conn: psycopg.Connection) -> dict[str, list[tuple[str, str, bool]]]:
    """Column metadata for each catalog, as this server reports it.

    Read from information_schema so the declared schema matches the server's version
    instead of a hardcoded guess, and so a catalog the server doesn't expose (an
    extension that isn't installed) is simply absent.
    """
    relations = [c.catalog_relation for c in POSTGRES_STATS_CATALOGS.values() if c.catalog_relation]
    columns: dict[str, list[tuple[str, str, bool]]] = {}
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT table_name, column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = ANY(%s)
            ORDER BY table_name, ordinal_position
            """,
            (relations,),
        )
        for table_name, column_name, data_type, is_nullable in cur:
            columns.setdefault(table_name, []).append((column_name, data_type, is_nullable == "YES"))
    return columns


def postgres_database_stats_source(
    *,
    tunnel: Callable[[], _GeneratorContextManager[tuple[str, int]]],
    user: str,
    password: str,
    database: str,
    schema_name: str,
    require_ssl: bool,
    logger: FilteringBoundLogger,
    source_schema: str | None = None,
) -> SourceResponse:
    """Build the response for one statistics table.

    `schema_name` is the table being synced (`system_tables.<catalog>`); `source_schema`
    is the Postgres schema the source imports from, which scopes the catalogs that carry
    schema attribution.
    """
    selected_schema = _normalize_selected_schema(source_schema)

    @contextmanager
    def open_connection() -> Iterator[psycopg.Connection]:
        with tunnel() as (host, port):
            with pg_connection(
                host=host, port=port, database=database, user=user, password=password, require_ssl=require_ssl
            ) as conn:
                # Autocommit so a failed catalog read (permissions, version quirks) is its
                # own transaction and can't poison anything that follows.
                conn.autocommit = True
                yield conn

    collectors: Mapping[str, Any] = {
        name: partial(catalog.collector, source_schema=selected_schema)
        for name, catalog in POSTGRES_STATS_CATALOGS.items()
    }
    return build_database_stats_source_response(
        schema_name=schema_name,
        catalogs=POSTGRES_STATS_CATALOGS,
        collectors=collectors,
        open_connection=open_connection,
        logger=logger,
    )
