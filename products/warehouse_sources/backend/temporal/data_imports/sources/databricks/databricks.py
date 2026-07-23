"""Databricks driver for PostHog's data-warehouse import pipeline.

Everything Databricks-specific — connection lifecycle (personal access
token vs OAuth M2M service principal auth), Unity Catalog
`information_schema` discovery, and the pipeline build — lives on
`DatabricksImplementation`. The source-class `DatabricksSource` is a thin
PostHog-layer wrapper that holds an instance and validates credentials.
"""

from __future__ import annotations

import collections
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, Optional

import structlog
from databricks import sql as databricks_sql
from databricks.sdk.core import (
    Config as DatabricksSdkConfig,
    oauth_service_principal,
)
from structlog.types import FilteringBoundLogger

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import log_connection_open
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql import BacktickIdentifierQuoter
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.implementation import (
    SourceMetadata,
    SQLSourceImplementation,
    TableStats,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.databricks import (
    DatabricksSourceConfig,
)
from products.warehouse_sources.backend.types import IncrementalFieldType

__all__ = [
    "DatabricksImplementation",
    "clean_databricks_host",
    "filter_databricks_incremental_fields",
]

_IDENTIFIER_QUOTER = BacktickIdentifierQuoter()

# Databricks native (server-side) parameters use PEP-249 `named` paramstyle (`:name` + dict).
_QUERY_BUILDER = SelectQueryBuilder(quoter=_IDENTIFIER_QUOTER, param_style=ParamStyle.NAMED)

# Unity Catalog metadata schema present in every catalog; never user data.
DATABRICKS_SYSTEM_SCHEMA = "information_schema"

# `fetchmany_arrow` size. CloudFetch already chunks the result set into presigned cloud-storage
# files behind the cursor, so this only bounds how many rows we materialize per yielded batch.
DEFAULT_DATABRICKS_FETCH_SIZE = 10_000


def filter_databricks_incremental_fields(
    columns: list[tuple[str, str, bool]],
) -> list[tuple[str, IncrementalFieldType, bool]]:
    results: list[tuple[str, IncrementalFieldType, bool]] = []
    for column_name, type, nullable in columns:
        type = type.lower()
        if type.startswith("timestamp"):
            # Covers TIMESTAMP and TIMESTAMP_NTZ.
            results.append((column_name, IncrementalFieldType.Timestamp, nullable))
        elif type == "date":
            results.append((column_name, IncrementalFieldType.Date, nullable))
        elif type in ("bigint", "int", "smallint", "tinyint") or type.startswith("decimal"):
            results.append((column_name, IncrementalFieldType.Numeric, nullable))

    return results


def clean_databricks_host(host: str) -> str:
    """Normalize a pasted workspace URL down to the bare hostname the connector expects."""
    host = host.strip()
    for prefix in ("https://", "http://"):
        if host.startswith(prefix):
            host = host[len(prefix) :]
    return host.rstrip("/")


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


class DatabricksImplementation(SQLSourceImplementation[DatabricksSourceConfig, Any, Any]):
    """Databricks driver implementation paired with `DatabricksSource`.

    One class owns everything Databricks-specific: the connection lifecycle
    (personal access token vs OAuth M2M service principal), the Unity Catalog
    `information_schema` batch queries used during schema listing, and the
    pipeline factory (`build_pipeline`).

    Databricks does not use the optional streaming-side hooks
    (`fetch_table_stats`, `fetch_average_row_size`, `get_table_metadata`) —
    it streams Arrow batches via `cursor.fetchmany_arrow()` (CloudFetch) and
    lets the base class return `None` for partition settings, matching the
    Snowflake driver.
    """

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    @contextmanager
    def connect(self, config: DatabricksSourceConfig) -> Iterator[Any]:
        """Open a Databricks SQL warehouse connection for the duration of the context.

        Branches on `config.auth_type.selection`: a personal access token is
        passed directly, while a service principal goes through the SDK's
        OAuth M2M credentials provider (1-hour tokens, auto-refreshed).

        Uses `config.catalog` as the session catalog so all two-part
        `schema.table` references resolve inside it; a blank schema
        (multi-schema import) leaves the session schema unset.
        """
        host = clean_databricks_host(config.host)
        auth_connect_args: dict[str, Any] = {}

        if config.auth_type.selection == "service_principal":
            client_id = config.auth_type.client_id
            client_secret = config.auth_type.client_secret

            def credentials_provider() -> Callable[[], dict[str, str]]:
                return oauth_service_principal(
                    DatabricksSdkConfig(
                        host=f"https://{host}",
                        client_id=client_id,
                        client_secret=client_secret,
                    )
                )

            auth_connect_args = {"credentials_provider": credentials_provider}
        else:
            auth_connect_args = {"access_token": config.auth_type.access_token}

        log_connection_open(db_host=host, via="vendor_https")
        connection = databricks_sql.connect(
            server_hostname=host,
            http_path=config.http_path,
            catalog=config.catalog,
            # A blank schema (multi-schema import) must reach the connector as None, not "" —
            # `schema=""` would try `USE SCHEMA ""`, an invalid identifier, and fail at connect time.
            schema=normalize_namespace(config.schema),
            user_agent_entry="PostHog",
            **auth_connect_args,
        )
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
        config: DatabricksSourceConfig,
        names: list[str] | None,
    ) -> dict[str, list[tuple[str, str, bool]]]:
        selected_schema = normalize_namespace(config.schema)
        qualify = selected_schema is None

        information_schema_columns = _IDENTIFIER_QUOTER.quote_qualified(
            config.catalog, DATABRICKS_SYSTEM_SCHEMA, "columns"
        )

        with conn.cursor() as cursor:
            if selected_schema is not None:
                cursor.execute(
                    "SELECT table_schema, table_name, column_name, data_type, is_nullable"
                    f" FROM {information_schema_columns}"
                    " WHERE table_schema = :schema"
                    " ORDER BY table_schema ASC, table_name ASC, ordinal_position ASC",
                    {"schema": selected_schema},
                )
            else:
                cursor.execute(
                    "SELECT table_schema, table_name, column_name, data_type, is_nullable"
                    f" FROM {information_schema_columns}"
                    " WHERE table_schema != :system_schema"
                    " ORDER BY table_schema ASC, table_name ASC, ordinal_position ASC",
                    {"system_schema": DATABRICKS_SYSTEM_SCHEMA},
                )
            result = cursor.fetchall()

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

    def get_primary_keys(
        self,
        conn: Any,
        config: DatabricksSourceConfig,
        tables: list[str],
    ) -> dict[str, list[str] | None]:
        """Detect informational primary-key constraints for the given tables.

        One batched query over the catalog's `information_schema` joins
        `table_constraints` to `key_column_usage`, so a blank-namespace
        discovery over a wide catalog stays a single round trip.

        Unity Catalog PK constraints are informational and optional — most
        tables won't have one, and legacy `hive_metastore` has no
        `information_schema` at all. Swallow and log failures so schema
        discovery keeps working without PKs (the base falls back to an `id`
        column when present).
        """
        result: dict[str, list[str] | None] = dict.fromkeys(tables)
        if not tables:
            return result

        default_schema = normalize_namespace(config.schema)
        display_by_pair: dict[tuple[str, str], str] = {}
        for display_name in tables:
            schema, table = _split_display_name(display_name, default_schema)
            if schema is None:
                continue
            display_by_pair[(schema, table)] = display_name

        table_constraints = _IDENTIFIER_QUOTER.quote_qualified(
            config.catalog, DATABRICKS_SYSTEM_SCHEMA, "table_constraints"
        )
        key_column_usage = _IDENTIFIER_QUOTER.quote_qualified(
            config.catalog, DATABRICKS_SYSTEM_SCHEMA, "key_column_usage"
        )

        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT kcu.table_schema, kcu.table_name, kcu.column_name, kcu.ordinal_position
                    FROM {table_constraints} AS tc
                    JOIN {key_column_usage} AS kcu
                      ON tc.constraint_catalog = kcu.constraint_catalog
                     AND tc.constraint_schema = kcu.constraint_schema
                     AND tc.constraint_name = kcu.constraint_name
                    WHERE tc.constraint_type = 'PRIMARY KEY'
                    """
                )

                keys_by_pair: dict[tuple[str, str], list[tuple[int, str]]] = collections.defaultdict(list)
                for table_schema, table_name, column_name, ordinal_position in cursor.fetchall():
                    keys_by_pair[(table_schema, table_name)].append((ordinal_position or 0, column_name))

                for pair, ordered in keys_by_pair.items():
                    display_key = display_by_pair.get(pair)
                    if display_key is None:
                        continue
                    keys = [column for _position, column in sorted(ordered, key=lambda item: item[0])]
                    if keys:
                        result[display_key] = keys
        except Exception as e:
            structlog.get_logger().warning("Failed to detect primary keys for Databricks tables", exc_info=e)

        return result

    def get_source_metadata(
        self,
        conn: Any,
        config: DatabricksSourceConfig,
        tables: list[str],
    ) -> SourceMetadata:
        """Stamp catalog/schema/table per discovered table so per-row routing can pin a namespace.

        The catalog is the connection's catalog (constant, display-only); the
        schema and unqualified table come from the `schema.table` display name,
        falling back to the configured schema for a single-schema source.
        """
        default_schema = normalize_namespace(config.schema)
        catalog_by_table: dict[str, str | None] = {}
        schema_by_table: dict[str, str | None] = {}
        table_name_by_table: dict[str, str | None] = {}
        for display_name in tables:
            schema, table = _split_display_name(display_name, default_schema)
            catalog_by_table[display_name] = config.catalog
            schema_by_table[display_name] = schema
            table_name_by_table[display_name] = table
        return SourceMetadata(
            catalog_by_table=catalog_by_table,
            schema_by_table=schema_by_table,
            table_name_by_table=table_name_by_table,
        )

    def get_incremental_filter(self) -> IncrementalFieldFilter:
        return filter_databricks_incremental_fields

    # ------------------------------------------------------------------
    # Per-cursor metadata — used during `build_pipeline`
    # ------------------------------------------------------------------

    def get_primary_keys_for_table(
        self,
        cursor: Any,
        catalog: str,
        schema: str,
        table_name: str,
    ) -> list[str] | None:
        """Return the primary-key column names for a single table, or None.

        Permission-sensitive like the schema-level `get_primary_keys` — swallow
        a failing lookup and return None so the pipeline falls back to a
        persisted or `id`-column primary key instead of crashing a merge.
        """
        table_constraints = _IDENTIFIER_QUOTER.quote_qualified(catalog, DATABRICKS_SYSTEM_SCHEMA, "table_constraints")
        key_column_usage = _IDENTIFIER_QUOTER.quote_qualified(catalog, DATABRICKS_SYSTEM_SCHEMA, "key_column_usage")

        try:
            cursor.execute(
                f"""
                SELECT kcu.column_name, kcu.ordinal_position
                FROM {table_constraints} AS tc
                JOIN {key_column_usage} AS kcu
                  ON tc.constraint_catalog = kcu.constraint_catalog
                 AND tc.constraint_schema = kcu.constraint_schema
                 AND tc.constraint_name = kcu.constraint_name
                WHERE tc.constraint_type = 'PRIMARY KEY'
                  AND kcu.table_schema = :schema
                  AND kcu.table_name = :table_name
                ORDER BY kcu.ordinal_position ASC
                """,
                {"schema": schema, "table_name": table_name},
            )
            keys = [row[0] for row in cursor.fetchall()]
        except Exception as e:
            structlog.get_logger().warning(
                "Failed to detect primary key for Databricks table",
                catalog=catalog,
                schema=schema,
                table_name=table_name,
                exc_info=e,
            )
            return None

        return keys if len(keys) > 0 else None

    def fetch_table_stats(
        self,
        cursor: Any,
        schema: str,
        table_name: str,
        logger: FilteringBoundLogger,
    ) -> TableStats | None:
        """Estimate the table's size and row count for partition sizing.

        `DESCRIBE DETAIL` returns a Delta table's `sizeInBytes` but no row count;
        `COUNT(*)` on a Delta table is metadata-optimized (answered from file
        statistics, no scan). Non-Delta objects (views, federated tables) make
        `DESCRIBE DETAIL` raise or return no size — `get_partition_settings`
        treats any failure here as "no stats" and skips partition sizing.

        `sizeInBytes` is the compressed on-disk size, so the derived average row
        size is an underestimate and partitions come out larger than the byte
        target — acceptable for a best-effort estimate.
        """
        table_ref = _IDENTIFIER_QUOTER.quote_qualified(schema, table_name)

        cursor.execute(f"DESCRIBE DETAIL {table_ref}")
        detail_row = cursor.fetchone()
        if detail_row is None or cursor.description is None:
            return None
        size_index = next((i for i, column in enumerate(cursor.description) if column[0] == "sizeInBytes"), -1)
        if size_index == -1:
            return None
        size_in_bytes = detail_row[size_index]
        if not size_in_bytes:
            return None

        cursor.execute(f"SELECT COUNT(*) FROM {table_ref}")
        count_row = cursor.fetchone()
        if count_row is None:
            return None
        row_count = int(count_row[0] or 0)
        if row_count == 0:
            return None

        return TableStats(table_size_bytes=int(size_in_bytes), row_count=row_count)

    # ------------------------------------------------------------------
    # Pipeline build — the `SourceResponse` for a single table
    # ------------------------------------------------------------------

    def build_pipeline(self, config: DatabricksSourceConfig, inputs: SourceInputs) -> SourceResponse:
        # Per-row routing: a multi-schema row pins its own namespace via `schema_metadata`,
        # a legacy single-schema row falls back to `config.schema`. The catalog is fixed
        # per connection. `response_name` preserves the legacy Delta subdir (`dwh_storage_key`).
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
            with connection.cursor() as cursor:
                primary_keys = self.get_primary_keys_for_table(cursor, config.catalog, schema, table_name)
                # The session catalog is pinned at connect time, so two-part `schema.table`
                # references always resolve inside `config.catalog`.
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
                rows_to_sync = self.get_rows_to_sync(cursor, query.sql, query.params, logger)
                # Partition sizing only pays off on incremental merges (same as MSSQL/MySQL) —
                # full refreshes rewrite the whole table regardless, so skip the extra probes.
                partition_settings = (
                    self.get_partition_settings(cursor, schema, table_name, logger)
                    if inputs.should_use_incremental_field
                    else None
                )

        def get_rows() -> Iterator[Any]:
            with self.connect(config) as streaming_connection:
                with streaming_connection.cursor() as streaming_cursor:
                    logger.debug(f"Databricks query: {query.sql}")
                    streaming_cursor.execute(query.sql, query.params)

                    while True:
                        table = streaming_cursor.fetchmany_arrow(DEFAULT_DATABRICKS_FETCH_SIZE)
                        if table.num_rows == 0:
                            break
                        yield table

        return SourceResponse(
            name=location.response_name,
            items=get_rows,
            primary_keys=primary_keys,
            partition_count=partition_settings.partition_count if partition_settings else None,
            partition_size=partition_settings.partition_size if partition_settings else None,
            rows_to_sync=rows_to_sync,
        )
