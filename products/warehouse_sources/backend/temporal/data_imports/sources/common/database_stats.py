"""Shared definitions for the opt-in database-statistics schemas.

SQL-family sources can offer a "Sync database statistics" toggle. When enabled, the
source injects a fixed set of synthetic schemas into its ``get_schemas()`` output —
they materialize as ordinary ``ExternalDataSchema`` rows, sync on the source's normal
schedule, and land as queryable warehouse tables. Each sync run appends one snapshot
of the engine's statistics catalogs (``pg_stat_*`` on Postgres, ``performance_schema``
on MySQL, …), tagged with ``collected_at``/``snapshot_id``. Counters are stored raw
and cumulative; deltas/rates are derived downstream over consecutive snapshots.

This module owns the engine-agnostic parts: schema names, normalized column sets, and
the ``SourceSchema`` builder. Engine-specific collection lives with each source (e.g.
``sources/postgres/stats.py``).
"""

import uuid
from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from typing import Any

import structlog
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

DATABASE_STATS_QUERIES = "database_stats_queries"
DATABASE_STATS_TABLES = "database_stats_tables"
DATABASE_STATS_INDEXES = "database_stats_indexes"
DATABASE_STATS_SERVER = "database_stats_server"

DATABASE_STATS_SCHEMA_NAMES: tuple[str, ...] = (
    DATABASE_STATS_QUERIES,
    DATABASE_STATS_TABLES,
    DATABASE_STATS_INDEXES,
    DATABASE_STATS_SERVER,
)

_DESCRIPTIONS: dict[str, str] = {
    DATABASE_STATS_QUERIES: (
        "Per-statement execution statistics snapshots (calls, total/mean time, rows, cache blocks). "
        "Counters are cumulative since the engine's last stats reset."
    ),
    DATABASE_STATS_TABLES: (
        "Per-table statistics snapshots: size, live/dead rows, sequential vs index scans, vacuum/analyze timestamps."
    ),
    DATABASE_STATS_INDEXES: "Per-index statistics snapshots: size, scan counts, uniqueness, definition.",
    DATABASE_STATS_SERVER: (
        "Server-level metrics snapshots (one row per metric): version, connections, cache hit, "
        "deadlocks, replication lag, key settings."
    ),
}

# Normalized, engine-agnostic column sets as (name, type, nullable) — the same tuple shape
# discovery produces for real tables. Engine-specific values that don't fit go in `extra`.
DATABASE_STATS_COLUMNS: dict[str, list[tuple[str, str, bool]]] = {
    DATABASE_STATS_QUERIES: [
        ("collected_at", "timestamp with time zone", False),
        ("snapshot_id", "text", False),
        ("query_fingerprint", "text", True),
        ("query_text", "text", True),
        ("calls", "bigint", True),
        ("total_exec_time_ms", "double precision", True),
        ("mean_exec_time_ms", "double precision", True),
        ("rows_processed", "bigint", True),
        ("cache_hit_blocks", "bigint", True),
        ("cache_read_blocks", "bigint", True),
        ("temp_blocks_written", "bigint", True),
        ("extra", "text", True),
    ],
    DATABASE_STATS_TABLES: [
        ("collected_at", "timestamp with time zone", False),
        ("snapshot_id", "text", False),
        ("schema_name", "text", False),
        ("table_name", "text", False),
        ("total_size_bytes", "bigint", True),
        ("row_estimate", "bigint", True),
        ("live_rows", "bigint", True),
        ("dead_rows", "bigint", True),
        ("seq_scans", "bigint", True),
        ("index_scans", "bigint", True),
        ("mods_since_analyze", "bigint", True),
        ("last_vacuum_at", "timestamp with time zone", True),
        ("last_autovacuum_at", "timestamp with time zone", True),
        ("last_analyze_at", "timestamp with time zone", True),
        ("last_autoanalyze_at", "timestamp with time zone", True),
        ("extra", "text", True),
    ],
    DATABASE_STATS_INDEXES: [
        ("collected_at", "timestamp with time zone", False),
        ("snapshot_id", "text", False),
        ("schema_name", "text", False),
        ("table_name", "text", False),
        ("index_name", "text", False),
        ("index_size_bytes", "bigint", True),
        ("index_scans", "bigint", True),
        ("is_unique", "boolean", True),
        ("is_primary", "boolean", True),
        ("definition", "text", True),
        ("extra", "text", True),
    ],
    DATABASE_STATS_SERVER: [
        ("collected_at", "timestamp with time zone", False),
        ("snapshot_id", "text", False),
        ("metric_name", "text", False),
        ("metric_value", "double precision", True),
        ("metric_text", "text", True),
        ("extra", "text", True),
    ],
}

_COLLECTED_AT_FIELD: IncrementalField = {
    "label": "collected_at",
    "type": IncrementalFieldType.DateTime,
    "field": "collected_at",
    "field_type": IncrementalFieldType.DateTime,
    # Synthetic append-only tables — there is no source-side index to scan, so never
    # surface the unindexed-cursor warning.
    "is_indexed": True,
}


def is_database_stats_schema(schema_name: str) -> bool:
    """Whether an ExternalDataSchema name refers to an injected stats schema."""
    return schema_name in DATABASE_STATS_SCHEMA_NAMES


def database_stats_enabled(config: Any) -> bool:
    """Whether a source config opts into database statistics.

    Sources without the toggle in their config (every non-SQL-family source today) have
    no ``database_stats`` attribute, so this is False — the single guard that keeps both
    schema injection and pipeline routing inert everywhere the feature isn't offered.
    """
    stats_config = getattr(config, "database_stats", None)
    return stats_config is not None and bool(stats_config.enabled)


def maybe_append_database_stats_schemas(
    config: Any, schemas: list[SourceSchema], names: list[str] | None
) -> list[SourceSchema]:
    """Append the stats schemas to a discovery listing when the config opts in.

    Honors the caller's ``names`` filter the same way discovery does, so a listing
    refresh scoped to specific tables never resurrects unrequested stats schemas.
    """
    if not database_stats_enabled(config):
        return schemas
    stats_schemas = build_database_stats_source_schemas([s.name for s in schemas])
    if names is not None:
        requested = set(names)
        stats_schemas = [s for s in stats_schemas if s.name in requested]
    return [*schemas, *stats_schemas]


def build_database_stats_source_schemas(discovered_names: list[str]) -> list[SourceSchema]:
    """The ``SourceSchema`` entries a source appends to discovery when stats are enabled.

    Skips any stats schema whose name collides with a real discovered table (comparing
    unqualified tails, matching ``sync_old_schemas_with_new_schemas``'s bare↔qualified
    equivalence) — a collision would wrongly route the user's own table to the stats
    collector.
    """
    discovered_tails = {name.rpartition(".")[2] for name in discovered_names}

    schemas: list[SourceSchema] = []
    for name in DATABASE_STATS_SCHEMA_NAMES:
        if name in discovered_tails:
            structlog.get_logger().warning(
                "Skipping database stats schema: name collides with a discovered table",
                schema_name=name,
            )
            continue
        schemas.append(
            SourceSchema(
                name=name,
                # Append-only snapshots: never merged, so incremental (merge) is off and the
                # default sync settings land on `append` with `collected_at` as the cursor.
                supports_incremental=False,
                supports_append=True,
                incremental_fields=[_COLLECTED_AT_FIELD],
                columns=DATABASE_STATS_COLUMNS[name],
                description=_DESCRIPTIONS[name],
                should_sync_default=True,
            )
        )
    return schemas


# One collector per stats schema: (connection, logger, collected_at, snapshot_id) -> rows.
# The connection is engine-specific (psycopg, pymysql, …) so it stays untyped here.
DatabaseStatsCollector = Callable[[Any, FilteringBoundLogger, datetime, str], list[dict[str, Any]]]


def build_database_stats_source_response(
    *,
    schema_name: str,
    collectors: Mapping[str, DatabaseStatsCollector],
    open_connection: Callable[[], AbstractContextManager[Any]],
    logger: FilteringBoundLogger,
) -> SourceResponse:
    """The engine-agnostic harness for a stats sync run.

    Owns everything that isn't a catalog query: the snapshot identity, lazy connection
    lifecycle, the collection-failure guard (a family the credentials can't read appends
    an empty snapshot, never a failed job), and the SourceResponse shape. Engines supply
    their collector mapping and a connection factory (tunnel + driver + autocommit).
    """
    collector = collectors.get(schema_name)
    if collector is None:
        raise ValueError(f"Unknown database stats schema: {schema_name}")

    def items() -> Iterator[dict[str, Any]]:
        collected_at = datetime.now(UTC)
        snapshot_id = uuid.uuid4().hex
        with open_connection() as conn:
            try:
                rows = collector(conn, logger, collected_at, snapshot_id)
            except Exception as e:
                logger.warning(
                    f"database_stats: collection failed for {schema_name}, appending empty snapshot",
                    error=str(e),
                )
                rows = []
        logger.info(f"database_stats: collected {len(rows)} rows for {schema_name}")
        yield from rows

    return SourceResponse(name=schema_name, items=items, primary_keys=None)
