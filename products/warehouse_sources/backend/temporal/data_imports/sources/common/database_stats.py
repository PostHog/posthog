"""Shared plumbing for the opt-in database-statistics schemas.

SQL-family sources can offer a "Sync database statistics" toggle. When enabled, the
source injects one synthetic schema per statistics catalog it knows how to read. They
materialize as ordinary ``ExternalDataSchema`` rows, sync on the source's normal
schedule, and land as queryable warehouse tables.

The synthetic schemas are presented as tables in a ``system_tables`` schema — e.g.
``system_tables.pg_stat_user_tables`` — so they look and behave like any other
multi-schema source table.

Each sync run appends one snapshot of the catalog **as the engine exposes it**: the
engine's own column names, plus ``collected_at``/``snapshot_id`` to identify the
snapshot and, where a size or definition is only available as a function call rather
than a column, a small number of clearly-named computed columns. Nothing is renamed,
reshaped, or dropped — a normalized cross-engine view belongs downstream, where it can
be rewritten without re-syncing, rather than baked into collection where it would be
lossy and permanent.

Counters stay raw and cumulative; deltas are derived downstream over consecutive
snapshots.

This module owns the engine-agnostic parts: the pseudo-schema name, the catalog
descriptor, the ``SourceSchema`` builder, and the collection harness. Engine-specific
catalog queries live with each source (e.g. ``sources/postgres/stats.py``).
"""

import uuid
import dataclasses
from collections.abc import Callable, Iterator, Mapping
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from typing import Any

import structlog
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# The pseudo-schema the statistics tables are presented under. Sources qualify their
# table names with the owning schema already, so these slot into the same naming.
DATABASE_STATS_SCHEMA = "system_tables"

# Columns the harness stamps on every snapshot row, ahead of the catalog's own columns.
SNAPSHOT_COLUMNS: list[tuple[str, str, bool]] = [
    ("collected_at", "timestamp with time zone", False),
    ("snapshot_id", "text", False),
]

# What the harness calls: (connection, logger, collected_at, snapshot_id) -> rows. The
# connection is engine-specific (psycopg, pymysql, …) so it stays untyped here.
DatabaseStatsCollector = Callable[[Any, FilteringBoundLogger, datetime, str], list[dict[str, Any]]]

# What a catalog stores. Engines may take extra keyword arguments of their own (Postgres
# passes the source's schema scope) and bind them before handing collectors to the
# harness, so the stored signature is looser than the one above.
CatalogCollector = Callable[..., list[dict[str, Any]]]


@dataclasses.dataclass(frozen=True)
class DatabaseStatsCatalog:
    """One statistics catalog a source can snapshot.

    ``table_name`` is the engine's own name for it (``pg_stat_user_tables``), which
    becomes the synthetic table name. ``catalog_relation`` is the relation to read
    column metadata from when the table mirrors a catalog one-for-one; leave it None for
    a derived table and declare ``static_columns`` instead. ``computed_columns`` are the
    extra columns the collector selects on top of the catalog's own (sizes and
    definitions that the engine only exposes as functions).
    """

    table_name: str
    description: str
    collector: CatalogCollector
    catalog_relation: str | None = None
    computed_columns: tuple[tuple[str, str, bool], ...] = ()
    static_columns: tuple[tuple[str, str, bool], ...] = ()


def stats_table_name(table_name: str) -> str:
    """The schema name a statistics catalog is presented as."""
    return f"{DATABASE_STATS_SCHEMA}.{table_name}"


_COLLECTED_AT_FIELD: IncrementalField = {
    "label": "collected_at",
    "type": IncrementalFieldType.DateTime,
    "field": "collected_at",
    "field_type": IncrementalFieldType.DateTime,
    # Synthetic append-only tables — there is no source-side index to scan, so never
    # surface the unindexed-cursor warning.
    "is_indexed": True,
}


def database_stats_enabled(config: Any) -> bool:
    """Whether a source config opts into database statistics.

    Sources without the toggle in their config (every non-SQL-family source today) have
    no ``database_stats`` attribute, so this is False — the single guard that keeps both
    schema injection and pipeline routing inert everywhere the feature isn't offered.
    """
    stats_config = getattr(config, "database_stats", None)
    return stats_config is not None and bool(stats_config.enabled)


def is_database_stats_schema(schema_name: str, catalogs: Mapping[str, DatabaseStatsCatalog]) -> bool:
    """Whether a schema name refers to one of this source's statistics catalogs."""
    return schema_name in {stats_table_name(name) for name in catalogs}


def is_database_stats_schema_row(
    schema_name: str, schema_metadata: dict[str, Any] | None, catalogs: Mapping[str, DatabaseStatsCatalog]
) -> bool:
    """Whether a concrete schema row is an injected statistics table, not a user's own.

    The name alone can't decide: a user could have a real schema called ``system_tables``
    holding a table of the same name. Discovered tables get ``source_table_name``
    persisted into their reconciled ``schema_metadata``; injected rows never do — so a
    row that names a real source table always wins the normal table-sync path.
    """
    if not is_database_stats_schema(schema_name, catalogs):
        return False
    return not (schema_metadata or {}).get("source_table_name")


def build_database_stats_schemas(
    catalogs: Mapping[str, DatabaseStatsCatalog],
    columns_by_table: Mapping[str, list[tuple[str, str, bool]]],
    discovered_names: list[str],
    names: list[str] | None = None,
) -> list[SourceSchema]:
    """The ``SourceSchema`` entries a source appends to discovery when stats are enabled.

    ``columns_by_table`` carries the catalog's own columns as the server reports them, so
    the declared schema matches the server's version rather than a hardcoded guess. A
    catalog the server doesn't expose (an extension that isn't installed) simply has no
    entry and is skipped.

    Skips any catalog whose name collides with a real discovered table, comparing both
    the qualified name and the unqualified tail to match
    ``sync_old_schemas_with_new_schemas``'s bare↔qualified equivalence — a collision
    would wrongly route the user's own table to the statistics collector.
    """
    discovered = set(discovered_names)
    discovered_tails = {name.rpartition(".")[2] for name in discovered_names}

    schemas: list[SourceSchema] = []
    for catalog in catalogs.values():
        name = stats_table_name(catalog.table_name)
        if names is not None and name not in names:
            continue

        if name in discovered or catalog.table_name in discovered_tails:
            structlog.get_logger().warning(
                "Skipping database stats table: name collides with a discovered table",
                schema_name=name,
            )
            continue

        catalog_columns = list(catalog.static_columns) or columns_by_table.get(catalog.table_name, [])
        if not catalog_columns:
            continue

        schemas.append(
            SourceSchema(
                name=name,
                # Append-only snapshots: never merged, so incremental (merge) is off and
                # the default sync settings land on `append` with `collected_at` as the
                # cursor.
                supports_incremental=False,
                supports_append=True,
                incremental_fields=[_COLLECTED_AT_FIELD],
                columns=[*SNAPSHOT_COLUMNS, *catalog_columns, *catalog.computed_columns],
                description=catalog.description,
                should_sync_default=True,
            )
        )
    return schemas


def build_database_stats_source_response(
    *,
    schema_name: str,
    catalogs: Mapping[str, DatabaseStatsCatalog],
    collectors: Mapping[str, DatabaseStatsCollector],
    open_connection: Callable[[], AbstractContextManager[Any]],
    logger: FilteringBoundLogger,
) -> SourceResponse:
    """The engine-agnostic harness for one statistics sync run.

    Owns everything that isn't a catalog query: the snapshot identity, lazy connection
    lifecycle, the collection-failure guard (a catalog the credentials can't read appends
    an empty snapshot, never a failed job), and the SourceResponse shape.
    """
    table_name = schema_name.rpartition(".")[2]
    if table_name not in catalogs:
        raise ValueError(f"Unknown database stats table: {schema_name}")
    collector = collectors[table_name]

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


def snapshot_rows(
    cursor: Any, collected_at: datetime, snapshot_id: str, limit: int | None = None
) -> list[dict[str, Any]]:
    """Materialize an executed cursor as snapshot rows, keyed by the engine's own columns.

    The catalog's columns pass through untouched; only the snapshot identity is added.
    """
    column_names = [column.name for column in cursor.description]
    rows: list[dict[str, Any]] = []
    for row in cursor:
        rows.append({"collected_at": collected_at, "snapshot_id": snapshot_id, **dict(zip(column_names, row))})
        if limit is not None and len(rows) >= limit:
            break
    return rows
