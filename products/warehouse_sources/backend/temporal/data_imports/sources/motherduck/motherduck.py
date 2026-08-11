"""MotherDuck driver for PostHog's data-warehouse import pipeline.

MotherDuck is DuckDB served from the cloud, so the client is the ordinary
`duckdb` package pointed at an `md:<database>` connection string carrying a
MotherDuck access token. Everything MotherDuck-specific — connection string
assembly, `information_schema` discovery, and the pipeline build — lives on
`MotherDuckImplementation`. The source-class `MotherduckSource` is a thin
PostHog-layer wrapper that holds an instance and validates credentials.

DuckDB runs in-process inside the Temporal worker, so this driver bounds both
what DuckDB may allocate (`DUCKDB_LOCAL_CONFIG`) and how many rows it
materializes at once (an Arrow record-batch reader rather than a full fetch).
"""

from __future__ import annotations

import re
import collections
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Optional
from urllib.parse import urlencode

import duckdb
import pyarrow as pa
import structlog

from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import log_connection_open
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql import AnsiIdentifierQuoter
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.implementation import (
    SourceMetadata,
    SQLSourceImplementation,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.incremental import (
    IncrementalFieldFilter,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.location import (
    normalize_namespace,
    resolve_source_location,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.query_builder import (
    ParamStyle,
    SelectQueryBuilder,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.motherduck import (
    MotherduckSourceConfig,
)
from products.warehouse_sources.backend.types import IncrementalFieldType

__all__ = [
    "MotherDuckImplementation",
    "build_motherduck_connection_string",
    "filter_motherduck_incremental_fields",
]

_IDENTIFIER_QUOTER = AnsiIdentifierQuoter()

# DuckDB binds `?` placeholders positionally from a list.
_QUERY_BUILDER = SelectQueryBuilder(quoter=_IDENTIFIER_QUOTER, param_style=ParamStyle.QMARK)

# MotherDuck is a single global service — there is no per-account hostname to configure.
MOTHERDUCK_SERVICE_HOST = "api.motherduck.com"

# DuckDB's catalog metadata schemas. `main` is a real user schema in DuckDB, not a system one.
MOTHERDUCK_SYSTEM_SCHEMAS = ("information_schema", "pg_catalog")

# Rows materialized per Arrow batch. Bounds resident memory: DuckDB shares this process.
DEFAULT_MOTHERDUCK_FETCH_SIZE = 5_000

# DuckDB otherwise sizes itself against the whole host (80% of RAM, one thread per core), which is
# the wrong budget for a library sharing a worker with the rest of the import pipeline.
DUCKDB_LOCAL_CONFIG: dict[str, Any] = {"memory_limit": "2GB", "threads": 2}

# The database name is interpolated into the `md:` connection string, so anything outside this
# allowlist could smuggle extra connection parameters in alongside the token.
_VALID_DATABASE_NAME = re.compile(r"^[A-Za-z0-9_.\-$]+$")


def build_motherduck_connection_string(database: str, access_token: str) -> str:
    """Assemble the `md:<database>?motherduck_token=…` DSN duckdb expects.

    Raises `ValueError` for a missing token or a database name that could alter
    the DSN's query string. Never log the return value: it carries the token.
    """
    name = database.strip()
    if not name:
        raise ValueError("Database name is missing")
    if not _VALID_DATABASE_NAME.match(name):
        raise ValueError(f"Invalid MotherDuck database name: {name!r}")
    if not access_token:
        raise ValueError("Access token is missing")
    return f"md:{name}?{urlencode({'motherduck_token': access_token})}"


def filter_motherduck_incremental_fields(
    columns: list[tuple[str, str, bool]],
) -> list[tuple[str, IncrementalFieldType, bool]]:
    results: list[tuple[str, IncrementalFieldType, bool]] = []
    for column_name, type, nullable in columns:
        type = type.lower()
        if type.startswith("timestamp"):
            # Covers TIMESTAMP, TIMESTAMP WITH TIME ZONE and the _S/_MS/_NS precision variants.
            results.append((column_name, IncrementalFieldType.Timestamp, nullable))
        elif type == "date":
            results.append((column_name, IncrementalFieldType.Date, nullable))
        elif type in (
            "bigint",
            "integer",
            "smallint",
            "tinyint",
            "hugeint",
            "ubigint",
            "uinteger",
            "usmallint",
            "utinyint",
            "uhugeint",
        ) or type.startswith("decimal"):
            results.append((column_name, IncrementalFieldType.Numeric, nullable))

    return results


def _split_display_name(display_name: str, default_schema: Optional[str]) -> tuple[Optional[str], str]:
    """Split a `schema.table` display name into `(schema, table)`.

    Multi-schema discovery qualifies every table as `schema.table`; a single-schema
    source keeps bare table names and falls back to the configured schema. The dotted
    form mirrors `resolve_source_location`'s self-heal so listing keys and per-row
    routing agree.
    """
    if "." in display_name:
        schema, _, table = display_name.partition(".")
        return (normalize_namespace(schema) or default_schema), table
    return default_schema, display_name


class MotherDuckImplementation(SQLSourceImplementation[MotherduckSourceConfig, Any, Any]):
    """MotherDuck driver implementation paired with `MotherduckSource`.

    Discovery reads DuckDB's `information_schema` and its `duckdb_constraints()` /
    `duckdb_tables()` catalog functions, all scoped to `current_database()` so the
    client's own `memory`, `system` and `temp` catalogs never surface as tables.

    Partition sizing is deliberately not implemented: DuckDB's catalog exposes an
    estimated row count but no on-disk byte size for an attached MotherDuck
    database, and the shared partition math needs bytes. The base class returns
    `None`, which falls back to default partition settings.
    """

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    @contextmanager
    def connect(self, config: MotherduckSourceConfig) -> Iterator[Any]:
        """Open a MotherDuck-backed DuckDB connection for the duration of the context."""
        connection_string = build_motherduck_connection_string(config.database, config.access_token)
        log_connection_open(db_host=MOTHERDUCK_SERVICE_HOST, via="vendor_https")
        connection = duckdb.connect(connection_string, config=dict(DUCKDB_LOCAL_CONFIG))
        try:
            yield connection
        finally:
            connection.close()

    # ------------------------------------------------------------------
    # Listing — batch queries run once during `get_schemas`
    # ------------------------------------------------------------------

    def get_columns(
        self,
        conn: Any,
        config: MotherduckSourceConfig,
        names: list[str] | None,
    ) -> dict[str, list[tuple[str, str, bool]]]:
        selected_schema = normalize_namespace(config.schema)
        qualify = selected_schema is None

        # Joined against `information_schema.tables` and restricted to `BASE TABLE`: a view's
        # columns are otherwise indistinguishable here from a real table's, but its definition
        # runs inside this Temporal worker at query time. A source owner could define a view over
        # a locally-executed DuckDB table function (e.g. reading the worker's filesystem) and have
        # it synced like any other table, so views are never offered for discovery.
        select = (
            "SELECT c.table_schema, c.table_name, c.column_name, c.data_type, c.is_nullable"
            " FROM information_schema.columns c"
            " JOIN information_schema.tables t"
            "   ON t.table_catalog = c.table_catalog"
            "  AND t.table_schema = c.table_schema"
            "  AND t.table_name = c.table_name"
            " WHERE c.table_catalog = current_database()"
            "   AND t.table_type = 'BASE TABLE'"
        )
        order = " ORDER BY c.table_schema ASC, c.table_name ASC, c.ordinal_position ASC"

        if selected_schema is not None:
            result = conn.execute(f"{select} AND c.table_schema = ?{order}", [selected_schema]).fetchall()
        else:
            placeholders = ", ".join("?" for _ in MOTHERDUCK_SYSTEM_SCHEMAS)
            result = conn.execute(
                f"{select} AND c.table_schema NOT IN ({placeholders}){order}",
                list(MOTHERDUCK_SYSTEM_SCHEMAS),
            ).fetchall()

        schema_list: dict[str, list[tuple[str, str, bool]]] = collections.defaultdict(list)
        for table_schema, table_name, column_name, data_type, is_nullable in result:
            display_name = f"{table_schema}.{table_name}" if qualify else table_name
            schema_list[display_name].append((column_name, data_type, is_nullable == "YES"))

        if names is not None:
            # Match qualified (`schema.table`) and bare (`table`) names — a row requested by its
            # qualified name can still map to a bare discovery key (or vice versa) mid-migration.
            available = dict(schema_list)
            filtered: dict[str, list[tuple[str, str, bool]]] = {}
            for name in names:
                if name in available:
                    filtered[name] = available[name]
                elif "." in name:
                    _schema, _, unqualified = name.partition(".")
                    if unqualified in available:
                        filtered[name] = available[unqualified]
            return filtered

        return dict(schema_list)

    def _display_names_by_pair(
        self,
        config: MotherduckSourceConfig,
        tables: list[str],
    ) -> dict[tuple[str, str], str]:
        """Index the requested display names by their `(schema, table)` pair."""
        default_schema = normalize_namespace(config.schema)
        pairs: dict[tuple[str, str], str] = {}
        for display_name in tables:
            schema, table = _split_display_name(display_name, default_schema)
            if schema is None:
                continue
            pairs[(schema, table)] = display_name
        return pairs

    def get_primary_keys(
        self,
        conn: Any,
        config: MotherduckSourceConfig,
        tables: list[str],
    ) -> dict[str, list[str] | None]:
        """Detect primary-key constraints for the given tables in one batched query.

        `duckdb_constraints()` already returns the key's columns in order, so no
        join or ordinal sort is needed. Most MotherDuck tables have no declared
        primary key, and the catalog function is permission-sensitive, so a failure
        degrades to "no keys found" and the base falls back to an `id` column.
        """
        result: dict[str, list[str] | None] = dict.fromkeys(tables)
        if not tables:
            return result

        display_by_pair = self._display_names_by_pair(config, tables)

        try:
            rows = conn.execute(
                "SELECT schema_name, table_name, constraint_column_names"
                " FROM duckdb_constraints()"
                " WHERE database_name = current_database() AND constraint_type = 'PRIMARY KEY'"
            ).fetchall()
        except Exception as e:
            structlog.get_logger().warning("Failed to detect primary keys for MotherDuck tables", exc_info=e)
            return result

        for schema_name, table_name, columns in rows:
            display_key = display_by_pair.get((schema_name, table_name))
            if display_key is None or not columns:
                continue
            result[display_key] = list(columns)

        return result

    def get_row_counts(
        self,
        conn: Any,
        config: MotherduckSourceConfig,
        tables: list[str],
    ) -> dict[str, int | None]:
        """Report each table's row count from DuckDB's catalog estimate.

        `estimated_size` is the planner's cardinality estimate, which keeps schema
        discovery to a single metadata query instead of a `COUNT(*)` per table
        billed against the customer's MotherDuck compute.
        """
        result: dict[str, int | None] = dict.fromkeys(tables)
        if not tables:
            return result

        display_by_pair = self._display_names_by_pair(config, tables)

        try:
            rows = conn.execute(
                "SELECT schema_name, table_name, estimated_size"
                " FROM duckdb_tables()"
                " WHERE database_name = current_database()"
            ).fetchall()
        except Exception as e:
            structlog.get_logger().warning("Failed to read row counts for MotherDuck tables", exc_info=e)
            return result

        for schema_name, table_name, estimated_size in rows:
            display_key = display_by_pair.get((schema_name, table_name))
            if display_key is None or estimated_size is None:
                continue
            result[display_key] = int(estimated_size)

        return result

    def get_source_metadata(
        self,
        conn: Any,
        config: MotherduckSourceConfig,
        tables: list[str],
    ) -> SourceMetadata:
        """Stamp catalog/schema/table per discovered table so per-row routing can pin a namespace."""
        default_schema = normalize_namespace(config.schema)
        catalog_by_table: dict[str, str | None] = {}
        schema_by_table: dict[str, str | None] = {}
        table_name_by_table: dict[str, str | None] = {}
        for display_name in tables:
            schema, table = _split_display_name(display_name, default_schema)
            catalog_by_table[display_name] = config.database
            schema_by_table[display_name] = schema
            table_name_by_table[display_name] = table
        return SourceMetadata(
            catalog_by_table=catalog_by_table,
            schema_by_table=schema_by_table,
            table_name_by_table=table_name_by_table,
        )

    def get_incremental_filter(self) -> IncrementalFieldFilter:
        return filter_motherduck_incremental_fields

    # ------------------------------------------------------------------
    # Per-connection metadata — used during `build_pipeline`
    # ------------------------------------------------------------------

    def get_primary_keys_for_table(
        self,
        conn: Any,
        schema: str,
        table_name: str,
    ) -> list[str] | None:
        """Return the primary-key column names for a single table, or None.

        Permission-sensitive like the schema-level `get_primary_keys` — a failing
        lookup degrades to None so the pipeline falls back to a persisted or
        `id`-column primary key instead of crashing a merge.
        """
        try:
            rows = conn.execute(
                "SELECT constraint_column_names"
                " FROM duckdb_constraints()"
                " WHERE database_name = current_database() AND constraint_type = 'PRIMARY KEY'"
                " AND schema_name = ? AND table_name = ?",
                [schema, table_name],
            ).fetchall()
        except Exception as e:
            structlog.get_logger().warning(
                "Failed to detect primary key for MotherDuck table",
                schema=schema,
                table_name=table_name,
                exc_info=e,
            )
            return None

        for (columns,) in rows:
            if columns:
                return list(columns)
        return None

    # ------------------------------------------------------------------
    # Pipeline build — the `SourceResponse` for a single table
    # ------------------------------------------------------------------

    def build_pipeline(self, config: MotherduckSourceConfig, inputs: SourceInputs) -> SourceResponse:
        # Per-row routing: a multi-schema row pins its own namespace via `schema_metadata`, a
        # single-schema row falls back to `config.schema`. The database is fixed per connection.
        location = resolve_source_location(inputs, config_namespace=config.schema)
        table_name = location.table_name
        schema = location.schema
        if not table_name:
            raise ValueError("Table name is missing")
        if not schema:
            raise ValueError("Schema is missing")

        logger = inputs.logger
        incremental_field = inputs.incremental_field if inputs.should_use_incremental_field else None
        incremental_field_type = inputs.incremental_field_type if inputs.should_use_incremental_field else None

        with self.connect(config) as connection:
            primary_keys = self.get_primary_keys_for_table(connection, schema, table_name)
            query = _QUERY_BUILDER.select_all(
                schema=schema,
                table_name=table_name,
                incremental_field=incremental_field,
                incremental_field_type=incremental_field_type,
                incremental_last_value=inputs.db_incremental_field_last_value,
                enabled_columns=inputs.enabled_columns,
                primary_keys=primary_keys,
                row_filters=inputs.row_filters,
            )
            rows_to_sync = self.get_rows_to_sync(connection, query.sql, query.params, logger)

        def get_rows() -> Iterator[pa.Table]:
            with self.connect(config) as streaming_connection:
                logger.debug(f"MotherDuck query: {query.sql}")
                reader = streaming_connection.execute(query.sql, query.params).to_arrow_reader(
                    DEFAULT_MOTHERDUCK_FETCH_SIZE
                )
                for batch in reader:
                    yield pa.Table.from_batches([batch], schema=reader.schema)

        return SourceResponse(
            name=location.response_name,
            items=get_rows,
            primary_keys=primary_keys,
            rows_to_sync=rows_to_sync,
        )
