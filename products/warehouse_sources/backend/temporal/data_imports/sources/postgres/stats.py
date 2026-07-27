"""Postgres statistics catalogs for the opt-in database-statistics schemas.

The default is to snapshot a catalog as the server exposes it — ``SELECT *`` plus the
snapshot identity, and named computed columns where Postgres only offers a value through
a function (relation sizes, index definitions, slot lag). So ``pg_stat_user_tables`` in
the warehouse has the columns a DBA expects from ``pg_stat_user_tables``, and a column
added by a later Postgres release arrives without a code change.

Four catalogs deviate, in every case to keep a secret out of the warehouse — these
tables are readable by every project member, which the source's own credentials are not:

- ``pg_settings`` is collected by allowlist, since custom GUC namespaces are
  user-defined and can hold application secrets (see ``_COLLECTED_SETTINGS``).
- ``pg_stat_statements`` keeps every row's counters but nulls query text outside
  ``_SAFE_STATEMENT_TEXT``, since utility statements are recorded verbatim, and strips
  comments from the text it keeps, since normalization preserves those too.
- ``pg_stat_user_indexes`` truncates each definition before its ``WHERE`` clause, since
  a partial index's predicate embeds column values.
- ``pg_stat_activity`` is aggregated to counts rather than mirrored, since its rows
  carry client addresses and session query text.

Every catalog degrades independently: one the credentials can't read appends an empty
snapshot with a warning rather than failing the sync, so a plain read-only user still
gets everything Postgres exposes to PUBLIC.
"""

import re
from collections.abc import Callable, Iterator, Mapping
from contextlib import _GeneratorContextManager, contextmanager
from datetime import datetime
from functools import partial
from typing import Any

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

# Row caps per snapshot. Every capped catalog is ranked first — statements by cumulative
# execution time, tables and indexes by size, buffer I/O by blocks touched — so the cap
# drops the least interesting rows rather than an arbitrary slice.
STATEMENTS_SNAPSHOT_LIMIT = 500
TABLES_SNAPSHOT_LIMIT = 5_000
INDEXES_SNAPSHOT_LIMIT = 10_000

# Restricts the table and index catalogs to the schema the source imports from. Applied
# only when the source is scoped to one schema; `pg_stat_statements` carries no schema
# attribution to filter on — see `_collect_statements`.
_SCHEMA_PREDICATE = sql.SQL("WHERE s.schemaname = {schema}")

# pg_settings is the one catalog collected by allowlist rather than in full. Its *rows*
# are user-extensible: an application can define custom parameters in any namespace
# (`pgrst.jwt_secret`, `app.api_token`), and a value set at server or role level shows up
# here. An unbounded namespace can't be filtered by denylist, and the built-in settings
# also expose filesystem paths and network topology (`data_directory`, `hba_file`,
# `listen_addresses`) that this feature has no use for. So name every setting we want.
# Grouped by what reads it, so it's obvious what a removal would break.
_COLLECTED_SETTINGS = (
    # Whether the statistics this feature relies on are being recorded at all. Without
    # these a detector can't tell "no problem" from "not measured" — `track_io_timing` is
    # off by default, which pins every block-timing column to zero.
    "track_counts",
    "track_io_timing",
    "track_activities",
    "track_functions",
    "shared_preload_libraries",
    "pg_stat_statements.max",
    "pg_stat_statements.track",
    "pg_stat_statements.track_utility",
    # Version, for gating advice.
    "server_version",
    "server_version_num",
    # Connection saturation: the denominator for pg_stat_activity_summary.
    "max_connections",
    "superuser_reserved_connections",
    "idle_in_transaction_session_timeout",
    "statement_timeout",
    "lock_timeout",
    "deadlock_timeout",
    # Memory and planner tuning — what turns "this table is scanned sequentially" into a
    # concrete recommendation. `random_page_cost` left at 4.0 on SSD storage is the
    # classic finding.
    "shared_buffers",
    "work_mem",
    "maintenance_work_mem",
    "effective_cache_size",
    "effective_io_concurrency",
    "random_page_cost",
    "seq_page_cost",
    "cpu_tuple_cost",
    "cpu_index_tuple_cost",
    "default_statistics_target",
    "temp_file_limit",
    "jit",
    "jit_above_cost",
    "max_parallel_workers",
    "max_parallel_workers_per_gather",
    "max_worker_processes",
    # Autovacuum: the dead-tuple and stale-statistics detectors advise by adjusting these.
    "autovacuum",
    "autovacuum_max_workers",
    "autovacuum_naptime",
    "autovacuum_vacuum_scale_factor",
    "autovacuum_analyze_scale_factor",
    "autovacuum_vacuum_threshold",
    "autovacuum_analyze_threshold",
    "autovacuum_vacuum_cost_limit",
    "autovacuum_vacuum_cost_delay",
    "vacuum_cost_limit",
    # WAL, checkpoints and replication: CDC prerequisites and WAL-growth analysis.
    "wal_level",
    "max_wal_size",
    "min_wal_size",
    "checkpoint_timeout",
    "checkpoint_completion_target",
    "synchronous_commit",
    "max_replication_slots",
    "max_wal_senders",
    "hot_standby",
    "wal_keep_size",
    # Whether slow queries are being logged at all.
    "log_min_duration_statement",
)

# pg_settings columns worth keeping. `sourcefile`/`sourceline` are dropped: they carry
# the on-disk config path, and the `source` column already says where a value came from
# ("configuration file", "default", "override") without disclosing the filesystem.
_SETTINGS_COLUMNS: tuple[tuple[str, str, bool], ...] = (
    ("name", "text", False),
    ("setting", "text", True),
    ("unit", "text", True),
    ("category", "text", True),
    ("short_desc", "text", True),
    ("context", "text", True),
    ("vartype", "text", True),
    ("source", "text", True),
    ("min_val", "text", True),
    ("max_val", "text", True),
    ("enumvals", "text", True),
    ("boot_val", "text", True),
    ("reset_val", "text", True),
    ("pending_restart", "boolean", True),
)

# Statement kinds whose text is safe to keep. Everything else has its `query` redacted
# while its counters are kept.
#
# pg_stat_statements normalizes constants in DML to `$1` placeholders, so those never
# carry a value. Utility statements are recorded as written, and the set that can embed a
# secret is not closed: besides the obvious `ALTER USER … PASSWORD '…'` and
# `CREATE SUBSCRIPTION … CONNECTION '…password=…'`, any custom GUC namespace can hold one
# (`ALTER DATABASE db SET app.api_token = '…'`, `SET app.api_token = '…'`), and those
# namespaces are user-defined. Naming the safe kinds is the only bound that holds — the
# same reason `pg_settings` is collected by allowlist.
#
# The maintenance commands are here because their timing is a real signal (a slow
# `VACUUM` or `REINDEX` is a finding) and, being utility statements, they are stored
# verbatim — safe only because their syntax takes identifiers, never a value.
#
# Two absences are deliberate, and neither should be added back:
#   - `EXPLAIN` is a utility statement that wraps an arbitrary one, so
#     `EXPLAIN SELECT … WHERE token = 'secret'` is stored with the literal intact. The
#     `SELECT` it wraps would have been jumbled; the `EXPLAIN` form is not.
#   - `COPY`, because `COPY … FROM PROGRAM` embeds a shell command.
_SAFE_STATEMENT_TEXT = re.compile(
    r"^\s*(?:select|insert|update|delete|with|merge|values|table|vacuum|analyze|reindex|cluster|refresh)\b",
    re.IGNORECASE,
)
_REDACTED_QUERY_COLUMN = "query"


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

    Statement text outside `_SAFE_STATEMENT_TEXT` is nulled, and what is kept has its
    comments stripped; the row and its counters are kept either way.
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

        return _sanitize_statement_text(snapshot_rows(cur, collected_at, snapshot_id))


def _strip_sql_comments(text: str) -> str:
    """Remove every SQL comment from a statement, collapsing the whitespace left behind.

    Normalization replaces constants but leaves comments verbatim — that is what makes
    query tagging (`/*controller=\'users\'*/`) work, and equally what would carry
    `/* api_token=… */` into the warehouse. Quoted spans are skipped so a literal or
    identifier containing `--` isn\'t mistaken for a comment, block comments nest the way
    Postgres nests them, and an unterminated comment drops the rest of the statement,
    which is the safe direction.
    """
    out: list[str] = []
    index, length, depth = 0, len(text), 0
    while index < length:
        if depth:
            if text.startswith("/*", index):
                depth += 1
                index += 2
            elif text.startswith("*/", index):
                depth -= 1
                index += 2
            else:
                index += 1
            continue

        char = text[index]
        if char in "'\"":
            end = index + 1
            while end < length:
                if text[end] == char:
                    if end + 1 < length and text[end + 1] == char:
                        end += 2
                        continue
                    break
                end += 1
            out.append(text[index : end + 1])
            index = end + 1
        elif text.startswith("/*", index):
            depth += 1
            index += 2
        elif text.startswith("--", index):
            newline = text.find("\n", index)
            if newline == -1:
                break
            index = newline
        else:
            out.append(char)
            index += 1
    return " ".join("".join(out).split())


def _sanitize_statement_text(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Null the text of statements outside `_SAFE_STATEMENT_TEXT`, and strip comments from
    the rest, keeping every row's counters.

    Redacting rather than dropping the row: the timing and call counts of a statement are
    never sensitive and are worth having, it\'s only the text that can carry a secret.
    """
    for row in rows:
        text = row.get(_REDACTED_QUERY_COLUMN)
        if not isinstance(text, str):
            continue
        row[_REDACTED_QUERY_COLUMN] = _strip_sql_comments(text) if _SAFE_STATEMENT_TEXT.match(text) else None
    return rows


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
                       split_part(pg_get_indexdef(s.indexrelid), ' WHERE ', 1) AS index_definition,
                       i.indpred IS NOT NULL AS is_partial
                FROM pg_stat_user_indexes s
                JOIN pg_index i ON i.indexrelid = s.indexrelid
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
                ORDER BY coalesce(s.heap_blks_read, 0) + coalesce(s.heap_blks_hit, 0) DESC
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
    """The tuning and instrumentation settings, by name.

    The one catalog collected by allowlist instead of in full — see `_COLLECTED_SETTINGS`
    for why, and `_SETTINGS_COLUMNS` for the columns kept. Cluster-wide by nature:
    settings aren't per-schema.
    """
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("SELECT {columns} FROM pg_settings WHERE name = ANY({names})").format(
                columns=sql.SQL(", ").join(sql.Identifier(name) for name, _, _ in _SETTINGS_COLUMNS),
                names=sql.Literal(list(_COLLECTED_SETTINGS)),
            )
        )
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
    """Backend counts by state for this database — deliberately an aggregate, not a mirror.

    Raw `pg_stat_activity` is a point-in-time list of live sessions carrying client
    addresses, usernames and (for the connecting role's own backends) query text. The
    signal wanted here is connection saturation, which a count answers, so this stays
    aggregated.

    The per-state breakdown covers this database only, so snapshots can't be used to
    watch a neighbouring database's activity pattern. `cluster_backends_total` is the one
    cross-database number kept, because `max_connections` is a cluster-wide limit and
    saturation is meaningless without the cluster-wide numerator — it's a single scalar
    with no breakdown behind it.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT coalesce(state, 'unknown') AS state,
                   count(*)::bigint AS backends,
                   (SELECT count(*) FROM pg_stat_activity)::bigint AS cluster_backends_total
            FROM pg_stat_activity
            WHERE datname = current_database()
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
                "statistics reset. Query text is kept for queries and maintenance commands and "
                "nulled for everything else, since utility statements are recorded verbatim and "
                "can embed credentials; comments are stripped from the text that is kept, since "
                "normalization preserves them. Requires the pg_stat_statements extension."
            ),
            collector=_collect_statements,
        ),
        DatabaseStatsCatalog(
            table_name="pg_stat_user_tables",
            description=(
                "Snapshots of pg_stat_user_tables: sequential and index scans, live and dead "
                "rows, and vacuum/analyze timestamps, plus total_size_bytes."
            ),
            collector=_collect_tables,
            computed_columns=(("total_size_bytes", "bigint", True),),
        ),
        DatabaseStatsCatalog(
            table_name="pg_stat_user_indexes",
            description=(
                "Snapshots of pg_stat_user_indexes: per-index scan counts, plus index_size_bytes, "
                "index_definition and is_partial. The definition stops before any WHERE clause, so a "
                "partial index's predicate — which can embed column values — is never collected; "
                "is_partial records that one existed."
            ),
            collector=_collect_indexes,
            computed_columns=(
                ("index_size_bytes", "bigint", True),
                ("index_definition", "text", True),
                ("is_partial", "boolean", True),
            ),
        ),
        DatabaseStatsCatalog(
            table_name="pg_statio_user_tables",
            description="Snapshots of pg_statio_user_tables: per-table buffer cache hits and disk reads.",
            collector=_collect_statio_tables,
        ),
        DatabaseStatsCatalog(
            table_name="pg_stat_database",
            description=(
                "Snapshots of pg_stat_database for this database: commits, rollbacks, cache hits, "
                "deadlocks, temp files and conflicts."
            ),
            collector=_collect_database,
        ),
        DatabaseStatsCatalog(
            table_name="pg_settings",
            description=(
                "Snapshots of the server's tuning and instrumentation settings — memory, planner "
                "costs, autovacuum, WAL and checkpoints, plus which statistics the server is "
                "recording. Collected by name: settings that can carry credentials, filesystem "
                "paths or network topology, and application-defined custom parameters, are never "
                "collected."
            ),
            collector=_collect_settings,
            static_columns=_SETTINGS_COLUMNS,
        ),
        DatabaseStatsCatalog(
            table_name="pg_replication_slots",
            description=(
                "Snapshots of pg_replication_slots for this database, plus retained_wal_bytes "
                "(NULL on a standby, where it can't be measured)."
            ),
            collector=_collect_replication_slots,
            computed_columns=(("retained_wal_bytes", "bigint", True),),
        ),
        DatabaseStatsCatalog(
            table_name="pg_stat_activity_summary",
            description=(
                "Backend counts by state for this database, plus the cluster-wide total that "
                "max_connections is measured against. An aggregate of pg_stat_activity rather "
                "than a copy, so no session details are collected."
            ),
            collector=_collect_activity_summary,
            static_columns=(
                ("state", "text", True),
                ("backends", "bigint", True),
                ("cluster_backends_total", "bigint", True),
            ),
        ),
    )
}


def fetch_postgres_stats_columns(conn: psycopg.Connection) -> dict[str, list[tuple[str, str, bool]]]:
    """Column metadata for the mirrored catalogs, as this server reports it.

    Catalogs that declare `static_columns` are skipped: they are projections we define
    (`pg_settings`, `pg_stat_activity_summary`), not mirrors of a server relation.

    Read from information_schema so the declared schema matches the server's version
    instead of a hardcoded guess, and so a catalog the server doesn't expose (an
    extension that isn't installed) is simply absent.
    """
    relations = [c.table_name for c in POSTGRES_STATS_CATALOGS.values() if not c.static_columns]
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

    `schema_name` is the catalog being synced (`pg_stat_user_tables`); `source_schema`
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
        collectors=collectors,
        open_connection=open_connection,
        logger=logger,
    )
