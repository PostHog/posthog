"""Postgres collector for the opt-in database-statistics schemas.

Each sync run of an injected ``database_stats_*`` schema appends one snapshot of the
matching statistics catalog, tagged with ``collected_at``/``snapshot_id``. Counters are
stored raw and cumulative (deltas are derived downstream). Every family degrades on
permission or availability problems by returning no rows for the parts it can't read —
a restricted user still gets everything Postgres exposes to PUBLIC, and a missing
``pg_stat_statements`` extension only empties the queries family.
"""

import json
from collections.abc import Callable, Iterator
from contextlib import _GeneratorContextManager, contextmanager
from datetime import datetime
from typing import Any

import psycopg
from psycopg import sql
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.database_stats import (
    DATABASE_STATS_INDEXES,
    DATABASE_STATS_QUERIES,
    DATABASE_STATS_SERVER,
    DATABASE_STATS_TABLES,
    DatabaseStatsCollector,
    build_database_stats_source_response,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres import pg_connection

# Row caps per snapshot. Queries are ranked by cumulative execution time so the cap keeps
# the statements that matter; tables/indexes are ranked by size for the same reason.
QUERIES_SNAPSHOT_LIMIT = 500
TABLES_SNAPSHOT_LIMIT = 5_000
INDEXES_SNAPSHOT_LIMIT = 10_000

# pg_stat_statements shows every statement's counters to any user, but replaces the text
# of other users' queries with this literal unless the role has pg_read_all_stats.
_INSUFFICIENT_PRIVILEGE_TEXT = "<insufficient privilege>"

# Settings worth snapshotting for health analysis: memory/planner knobs, autovacuum, and
# connection limits. Stored as text metrics (values keep Postgres' native unit strings).
_SETTINGS_OF_INTEREST = (
    "max_connections",
    "shared_buffers",
    "work_mem",
    "maintenance_work_mem",
    "effective_cache_size",
    "random_page_cost",
    "autovacuum",
    "autovacuum_vacuum_scale_factor",
    "autovacuum_analyze_scale_factor",
    "max_wal_size",
    "wal_level",
    "statement_timeout",
)


def _base_row(collected_at: datetime, snapshot_id: str) -> dict[str, Any]:
    return {"collected_at": collected_at, "snapshot_id": snapshot_id}


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


def _collect_queries(
    conn: psycopg.Connection, logger: FilteringBoundLogger, collected_at: datetime, snapshot_id: str
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        relation = _pg_stat_statements_relation(cur)
        if relation is None:
            logger.info("database_stats: pg_stat_statements is not installed, queries snapshot will be empty")
            return []

        # Column names changed in pg_stat_statements 1.8 (total_time -> total_exec_time);
        # try the modern names first and fall back for older extension versions.
        for time_cols in ("total_exec_time, mean_exec_time", "total_time, mean_time"):
            try:
                cur.execute(
                    sql.SQL(
                        """
                        SELECT queryid::text, query, calls, {time_cols}, rows,
                               shared_blks_hit, shared_blks_read, temp_blks_written
                        FROM {relation}
                        ORDER BY 4 DESC
                        LIMIT %s
                        """
                    ).format(time_cols=sql.SQL(time_cols), relation=relation),
                    (QUERIES_SNAPSHOT_LIMIT,),
                )
                break
            except psycopg.errors.UndefinedColumn:
                continue
        else:
            logger.warning("database_stats: pg_stat_statements has an unexpected column set, skipping")
            return []

        rows = []
        for queryid, query_text, calls, total_time, mean_time, n_rows, blks_hit, blks_read, temp_written in cur:
            rows.append(
                {
                    **_base_row(collected_at, snapshot_id),
                    "query_fingerprint": queryid,
                    # Without pg_read_all_stats other users' query text is masked — store
                    # NULL so downstream never treats the placeholder as a real statement.
                    "query_text": None if query_text == _INSUFFICIENT_PRIVILEGE_TEXT else query_text,
                    "calls": calls,
                    "total_exec_time_ms": float(total_time) if total_time is not None else None,
                    "mean_exec_time_ms": float(mean_time) if mean_time is not None else None,
                    "rows_processed": n_rows,
                    "cache_hit_blocks": blks_hit,
                    "cache_read_blocks": blks_read,
                    "temp_blocks_written": temp_written,
                    "extra": None,
                }
            )
        return rows


def _collect_tables(
    conn: psycopg.Connection, logger: FilteringBoundLogger, collected_at: datetime, snapshot_id: str
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT s.schemaname, s.relname,
                   pg_total_relation_size(s.relid),
                   c.reltuples::bigint,
                   s.n_live_tup, s.n_dead_tup, s.seq_scan, s.idx_scan, s.n_mod_since_analyze,
                   s.last_vacuum, s.last_autovacuum, s.last_analyze, s.last_autoanalyze,
                   io.heap_blks_hit, io.heap_blks_read
            FROM pg_stat_user_tables s
            JOIN pg_class c ON c.oid = s.relid
            LEFT JOIN pg_statio_user_tables io ON io.relid = s.relid
            ORDER BY 3 DESC
            LIMIT %s
            """,
            (TABLES_SNAPSHOT_LIMIT,),
        )
        rows = []
        for (
            schema_name,
            table_name,
            total_size,
            row_estimate,
            live_rows,
            dead_rows,
            seq_scans,
            index_scans,
            mods_since_analyze,
            last_vacuum,
            last_autovacuum,
            last_analyze,
            last_autoanalyze,
            heap_blks_hit,
            heap_blks_read,
        ) in cur:
            rows.append(
                {
                    **_base_row(collected_at, snapshot_id),
                    "schema_name": schema_name,
                    "table_name": table_name,
                    "total_size_bytes": total_size,
                    "row_estimate": row_estimate,
                    "live_rows": live_rows,
                    "dead_rows": dead_rows,
                    "seq_scans": seq_scans,
                    "index_scans": index_scans,
                    "mods_since_analyze": mods_since_analyze,
                    "last_vacuum_at": last_vacuum,
                    "last_autovacuum_at": last_autovacuum,
                    "last_analyze_at": last_analyze,
                    "last_autoanalyze_at": last_autoanalyze,
                    "extra": json.dumps({"heap_blks_hit": heap_blks_hit, "heap_blks_read": heap_blks_read}),
                }
            )
        return rows


def _collect_indexes(
    conn: psycopg.Connection, logger: FilteringBoundLogger, collected_at: datetime, snapshot_id: str
) -> list[dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT s.schemaname, s.relname, s.indexrelname,
                   pg_relation_size(s.indexrelid),
                   s.idx_scan,
                   i.indisunique, i.indisprimary,
                   pg_get_indexdef(s.indexrelid)
            FROM pg_stat_user_indexes s
            JOIN pg_index i ON i.indexrelid = s.indexrelid
            ORDER BY 4 DESC
            LIMIT %s
            """,
            (INDEXES_SNAPSHOT_LIMIT,),
        )
        rows = []
        for schema_name, table_name, index_name, size_bytes, idx_scan, is_unique, is_primary, definition in cur:
            rows.append(
                {
                    **_base_row(collected_at, snapshot_id),
                    "schema_name": schema_name,
                    "table_name": table_name,
                    "index_name": index_name,
                    "index_size_bytes": size_bytes,
                    "index_scans": idx_scan,
                    "is_unique": is_unique,
                    "is_primary": is_primary,
                    "definition": definition,
                    "extra": None,
                }
            )
        return rows


def _collect_server(
    conn: psycopg.Connection, logger: FilteringBoundLogger, collected_at: datetime, snapshot_id: str
) -> list[dict[str, Any]]:
    """Server-level metrics as one row per metric (EAV — the set is heterogeneous)."""
    base = _base_row(collected_at, snapshot_id)
    rows: list[dict[str, Any]] = []

    def _metric(name: str, value: float | None = None, text: str | None = None, extra: dict | None = None) -> None:
        rows.append(
            {
                **base,
                "metric_name": name,
                "metric_value": value,
                "metric_text": text,
                "extra": json.dumps(extra) if extra else None,
            }
        )

    def _probe(name: str, fn: Callable[[psycopg.Cursor], None]) -> None:
        # Each probe is its own cursor + guard: one unreadable view must not empty the
        # whole server snapshot (autocommit keeps a failed probe from poisoning the rest).
        try:
            with conn.cursor() as cur:
                fn(cur)
        except Exception as e:
            logger.warning("database_stats: server probe failed, skipping", probe=name, error=str(e))

    def _version(cur: psycopg.Cursor) -> None:
        cur.execute("SHOW server_version")
        row = cur.fetchone()
        if row:
            _metric("server_version", text=row[0])

    def _database_totals(cur: psycopg.Cursor) -> None:
        cur.execute(
            """
            SELECT numbackends, xact_commit, xact_rollback, blks_hit, blks_read,
                   deadlocks, temp_files, temp_bytes
            FROM pg_stat_database
            WHERE datname = current_database()
            """
        )
        row = cur.fetchone()
        if row is None:
            return
        for name, value in zip(
            (
                "numbackends",
                "xact_commit",
                "xact_rollback",
                "blks_hit",
                "blks_read",
                "deadlocks",
                "temp_files",
                "temp_bytes",
            ),
            row,
        ):
            _metric(name, value=float(value) if value is not None else None)

    def _connections(cur: psycopg.Cursor) -> None:
        cur.execute("SELECT count(*) FROM pg_stat_activity")
        row = cur.fetchone()
        if row:
            _metric("connections_total", value=float(row[0]))

    def _settings(cur: psycopg.Cursor) -> None:
        cur.execute(
            "SELECT name, setting, unit FROM pg_settings WHERE name = ANY(%s)",
            (list(_SETTINGS_OF_INTEREST),),
        )
        for name, setting, unit in cur:
            _metric(f"setting_{name}", text=setting, extra={"unit": unit} if unit else None)

    def _pg_stat_statements_installed(cur: psycopg.Cursor) -> None:
        cur.execute("SELECT count(*) FROM pg_extension WHERE extname = 'pg_stat_statements'")
        row = cur.fetchone()
        if row:
            _metric("extension_pg_stat_statements", value=float(row[0]))

    def _replication_slots(cur: psycopg.Cursor) -> None:
        # pg_current_wal_lsn() raises on a standby, so lag is only measurable on a primary.
        cur.execute("SELECT pg_is_in_recovery()")
        row = cur.fetchone()
        if row is None or row[0]:
            return
        cur.execute(
            """
            SELECT slot_name, active,
                   pg_wal_lsn_diff(pg_current_wal_lsn(), restart_lsn)
            FROM pg_replication_slots
            """
        )
        for slot_name, active, lag_bytes in cur:
            _metric(
                "replication_slot_lag_bytes",
                value=float(lag_bytes) if lag_bytes is not None else None,
                text=slot_name,
                extra={"active": bool(active)},
            )

    _probe("server_version", _version)
    _probe("database_totals", _database_totals)
    _probe("connections", _connections)
    _probe("settings", _settings)
    _probe("pg_stat_statements_installed", _pg_stat_statements_installed)
    _probe("replication_slots", _replication_slots)

    return rows


_COLLECTORS: dict[str, DatabaseStatsCollector] = {
    DATABASE_STATS_QUERIES: _collect_queries,
    DATABASE_STATS_TABLES: _collect_tables,
    DATABASE_STATS_INDEXES: _collect_indexes,
    DATABASE_STATS_SERVER: _collect_server,
}


def postgres_database_stats_source(
    *,
    tunnel: Callable[[], _GeneratorContextManager[tuple[str, int]]],
    user: str,
    password: str,
    database: str,
    schema_name: str,
    require_ssl: bool,
    logger: FilteringBoundLogger,
) -> SourceResponse:
    @contextmanager
    def open_connection() -> Iterator[psycopg.Connection]:
        with tunnel() as (host, port):
            with pg_connection(
                host=host, port=port, database=database, user=user, password=password, require_ssl=require_ssl
            ) as conn:
                # Autocommit so a failed probe (permissions, version quirks) is its own
                # transaction and can't poison the rest of the snapshot.
                conn.autocommit = True
                yield conn

    return build_database_stats_source_response(
        schema_name=schema_name,
        collectors=_COLLECTORS,
        open_connection=open_connection,
        logger=logger,
    )
