"""Snowflake driver for PostHog's data-warehouse import pipeline.

Everything Snowflake-specific — connection lifecycle (with password vs
keypair auth and the keypair tempfile dance), schema listing, per-cursor
metadata, and the dlt pipeline build — lives on
`SnowflakeImplementation`. The source-class `SnowflakeSource` is a thin
PostHog-layer wrapper that just holds an instance and validates
credentials.
"""

from __future__ import annotations

import collections
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Optional

import structlog
import snowflake.connector
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import serialization
from snowflake.connector.util_text import construct_hostname
from structlog.types import FilteringBoundLogger

from posthog.exceptions_capture import capture_exception

from products.warehouse_sources.backend.temporal.data_imports.pipelines.helpers import (
    incremental_type_to_initial_value,
    incremental_type_to_operator,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import log_connection_open
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql import (
    AnsiIdentifierQuoter,
    ValidatedRowFilter,
    compute_projected_columns,
    format_projected_select_clause,
    render_positional_conditions,
)
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SnowflakeSourceConfig
from products.warehouse_sources.backend.types import IncrementalFieldType

__all__ = [
    "SnowflakeImplementation",
    "filter_snowflake_incremental_fields",
]


def filter_snowflake_incremental_fields(
    columns: list[tuple[str, str, bool]],
) -> list[tuple[str, IncrementalFieldType, bool]]:
    results: list[tuple[str, IncrementalFieldType, bool]] = []
    for column_name, type, nullable in columns:
        type = type.lower()
        if type.startswith("timestamp"):
            results.append((column_name, IncrementalFieldType.Timestamp, nullable))
        elif type == "date":
            results.append((column_name, IncrementalFieldType.Date, nullable))
        elif type == "datetime":
            results.append((column_name, IncrementalFieldType.DateTime, nullable))
        elif type in ("number", "numeric"):
            results.append((column_name, IncrementalFieldType.Numeric, nullable))

    return results


_SNOWFLAKE_IDENTIFIER_QUOTER = AnsiIdentifierQuoter()

# Snowflake exposes one metadata schema per database; everything else is user data.
SNOWFLAKE_SYSTEM_SCHEMA = "INFORMATION_SCHEMA"

# Bound the connector's per-request retry budget. `network_timeout` defaults to infinite, so a
# stalled/half-open connection mid-request (peer or network drop) retries forever in the worker
# thread. The sync activities are threaded and the heartbeater runs on a separate event-loop task,
# so the stall isn't surfaced by a missed heartbeat — the activity just runs until Temporal's
# `start_to_close_timeout` cancels the thread mid socket-read, surfacing a misleading
# `WantReadError`/`CancelledError`. Bounding it turns the stall into a fast, retryable
# `OperationalError` well before the activity is cancelled. It applies per request, so it never caps
# a long-running streaming sync. Kept comfortably under the schema-discovery activity's 10-minute
# `start_to_close_timeout` while leaving ample room for legitimate per-request round-trips and retries.
_SNOWFLAKE_NETWORK_TIMEOUT_SECONDS = 300


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


def _display_by_pair(tables: list[str], default_schema: Optional[str]) -> dict[tuple[str, str], str]:
    """Map each resolvable `(schema, table)` back to its display name, dropping unresolved rows."""
    pairs: dict[tuple[str, str], str] = {}
    for display_name in tables:
        schema, table = _split_display_name(display_name, default_schema)
        if schema is None:
            continue
        pairs[(schema, table)] = display_name
    return pairs


def _build_query(
    database: str,
    schema: str,
    table_name: str,
    should_use_incremental_field: bool,
    incremental_field: Optional[str],
    incremental_field_type: Optional[IncrementalFieldType],
    db_incremental_field_last_value: Optional[Any],
    enabled_columns: list[str] | None = None,
    primary_keys: list[str] | None = None,
    row_filters: list[ValidatedRowFilter] | None = None,
) -> tuple[str, tuple[Any, ...]]:
    projected = compute_projected_columns(enabled_columns, primary_keys, incremental_field)
    select_clause = format_projected_select_clause(projected, _SNOWFLAKE_IDENTIFIER_QUOTER)
    table_ref = f"{database}.{schema}.{table_name}"

    # Positional param order: IDENTIFIER(%s), then any incremental value, then row-filter values.
    filter_conditions, filter_values = render_positional_conditions(row_filters or [], _SNOWFLAKE_IDENTIFIER_QUOTER)

    if not should_use_incremental_field:
        if filter_conditions:
            return (
                f"SELECT {select_clause} FROM IDENTIFIER(%s) WHERE {' AND '.join(filter_conditions)}",
                (table_ref, *filter_values),
            )
        return f"SELECT {select_clause} FROM IDENTIFIER(%s)", (table_ref,)

    if incremental_field is None or incremental_field_type is None:
        raise ValueError("incremental_field and incremental_field_type can't be None")

    if db_incremental_field_last_value is None:
        db_incremental_field_last_value = incremental_type_to_initial_value(incremental_field_type)

    operator = incremental_type_to_operator(incremental_field_type)
    quoted_field = _SNOWFLAKE_IDENTIFIER_QUOTER.quote(incremental_field)
    conditions = [f"{quoted_field} {operator} %s", *filter_conditions]
    return (
        f"SELECT {select_clause} FROM IDENTIFIER(%s) WHERE {' AND '.join(conditions)} ORDER BY {quoted_field} ASC",
        (table_ref, db_incremental_field_last_value, *filter_values),
    )


def _parse_clustering_key_leading_column(clustering_key: str | None) -> str | None:
    """Extract the leading column from a Snowflake CLUSTERING_KEY string.

    Snowflake stores clustering keys as expressions like ``LINEAR(col1, col2)``.
    We unwrap the optional ``LINEAR(...)`` envelope, take the first comma-
    separated entry, and return its identifier in the same case Snowflake uses
    for ``INFORMATION_SCHEMA.COLUMNS.COLUMN_NAME`` so the caller can compare
    directly: unquoted identifiers are uppercased (matching Snowflake's
    identifier resolution rules), quoted identifiers have the quotes stripped
    and their case preserved. Returns None if the entry is empty or appears to
    be a function expression rather than a plain column reference (we can't
    tell whether `DATE_TRUNC('day', x)` accelerates predicate pruning the same
    way).
    """
    if not clustering_key:
        return None
    expr = clustering_key.strip()
    if expr.upper().startswith("LINEAR("):
        if not expr.endswith(")"):
            return None
        expr = expr[len("LINEAR(") : -1]
    leading = expr.split(",", 1)[0].strip()
    if not leading or "(" in leading:
        return None
    if leading.startswith('"') and leading.endswith('"') and len(leading) >= 2:
        return leading[1:-1]
    return leading.upper()


def get_connection_metadata(config: SnowflakeSourceConfig) -> dict[str, str | None]:
    """Connection metadata persisted on a direct-query source for the HogQL executor."""
    return {
        "engine": "snowflake",
        "account_id": config.account_id,
        "warehouse": config.warehouse,
        "database": config.database,
        "schema": normalize_namespace(config.schema),
        "role": config.role,
        "user": config.auth_type.user,
    }


class SnowflakeImplementation(
    SQLSourceImplementation[SnowflakeSourceConfig, snowflake.connector.SnowflakeConnection, Any]
):
    """Snowflake driver implementation paired with `SnowflakeSource`.

    One class owns everything Snowflake-specific: the connection
    lifecycle (password vs keypair, with private-key tempfile cleanup),
    `information_schema`-style batch queries used during schema listing,
    per-cursor metadata used during the streaming sync (primary keys),
    and the dlt pipeline factory (`build_pipeline`).

    Snowflake does not currently use the optional streaming-side hooks
    (`fetch_table_stats`, `fetch_average_row_size`, `get_table_metadata`)
    — it streams via `cursor.fetch_arrow_batches()` and lets the base
    class return `None` for partition settings and the default chunk
    size. That preserves current behavior.
    """

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    @contextmanager
    def connect(
        self,
        config: SnowflakeSourceConfig,
    ) -> Iterator[snowflake.connector.SnowflakeConnection]:
        """Open a Snowflake connection for the duration of the context.

        Branches on `config.auth_type.selection`. In keypair mode the
        PEM private key is parsed in process and handed to the
        connector as DER bytes via `private_key=` — never written to
        disk, matching the streaming-side helper that the pre-refactor
        code used.

        Uses `config.schema` as the session schema when set; a blank schema
        (multi-schema import) leaves the session schema unset. All listing and
        sync queries fully qualify their references so the session schema does
        not affect their results.
        """
        auth_connect_args: dict[str, Any] = {}

        if config.auth_type.selection == "keypair" and config.auth_type.private_key is not None:
            p_key = serialization.load_pem_private_key(
                config.auth_type.private_key.encode("utf-8"),
                password=config.auth_type.passphrase.encode() if config.auth_type.passphrase else None,
                backend=default_backend(),
            )
            pkb = p_key.private_bytes(
                encoding=serialization.Encoding.DER,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
            auth_connect_args = {
                "user": config.auth_type.user,
                "private_key": pkb,
            }
        else:
            auth_connect_args = {
                "password": config.auth_type.password,
                "user": config.auth_type.user,
            }

        # construct_hostname is what the connector itself uses to derive the host from `account`.
        log_connection_open(db_host=construct_hostname(None, config.account_id), via="vendor_https")
        with snowflake.connector.connect(
            account=config.account_id,
            warehouse=config.warehouse,
            database=config.database,
            # A blank schema (multi-schema import) must reach the connector as None, not "" —
            # `schema=""` would try `USE SCHEMA ""`, an invalid identifier, and fail at connect time.
            schema=normalize_namespace(config.schema),
            role=config.role,
            network_timeout=_SNOWFLAKE_NETWORK_TIMEOUT_SECONDS,
            **auth_connect_args,
        ) as connection:
            yield connection

    # ------------------------------------------------------------------
    # Listing — batch queries run once during `get_schemas`
    # ------------------------------------------------------------------

    def get_columns(
        self,
        conn: snowflake.connector.SnowflakeConnection,
        config: SnowflakeSourceConfig,
        names: list[str] | None,
    ) -> dict[str, list[tuple[str, str, bool]]]:
        selected_schema = normalize_namespace(config.schema)
        qualify = selected_schema is None

        with conn.cursor() as cursor:
            if cursor is None:
                raise Exception("Can't create cursor to Snowflake")

            if selected_schema is not None:
                cursor.execute(
                    "SELECT table_schema, table_name, column_name, data_type, is_nullable"
                    " FROM information_schema.columns"
                    " WHERE table_schema = %(schema)s"
                    " ORDER BY table_schema ASC, table_name ASC",
                    {"schema": selected_schema},
                )
            else:
                cursor.execute(
                    "SELECT table_schema, table_name, column_name, data_type, is_nullable"
                    " FROM information_schema.columns"
                    " WHERE table_schema != %(system_schema)s"
                    " ORDER BY table_schema ASC, table_name ASC",
                    {"system_schema": SNOWFLAKE_SYSTEM_SCHEMA},
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
        conn: snowflake.connector.SnowflakeConnection,
        config: SnowflakeSourceConfig,
        tables: list[str],
    ) -> dict[str, list[str] | None]:
        """Detect primary keys for the given (possibly multi-schema) tables.

        Batches one `SHOW PRIMARY KEYS IN SCHEMA` per distinct namespace rather
        than one per table, so a blank-namespace discovery over a wide catalog
        stays bounded by schema count instead of table count.

        Permission-sensitive — some Snowflake roles can't see catalog-level PK
        metadata. Swallow and log per-schema failures so schema discovery keeps
        working without PKs.
        """
        result: dict[str, list[str] | None] = dict.fromkeys(tables)
        if not tables:
            return result

        display_by_pair = _display_by_pair(tables, normalize_namespace(config.schema))

        try:
            with conn.cursor() as cursor:
                if cursor is None:
                    raise Exception("Can't create cursor to Snowflake")

                for schema in sorted({schema for schema, _table in display_by_pair}):
                    try:
                        cursor.execute(
                            f"SHOW PRIMARY KEYS IN SCHEMA {_SNOWFLAKE_IDENTIFIER_QUOTER.quote_qualified(config.database, schema)}"
                        )
                        table_index = next(
                            (i for i, row in enumerate(cursor.description) if row.name == "table_name"), -1
                        )
                        column_index = next(
                            (i for i, row in enumerate(cursor.description) if row.name == "column_name"), -1
                        )
                        sequence_index = next(
                            (i for i, row in enumerate(cursor.description) if row.name == "key_sequence"), -1
                        )
                        if table_index == -1 or column_index == -1:
                            continue

                        keys_by_table: dict[str, list[tuple[int, str]]] = collections.defaultdict(list)
                        for row in cursor:
                            sequence = row[sequence_index] if sequence_index != -1 else 0
                            keys_by_table[row[table_index]].append((sequence, row[column_index]))

                        for table, ordered in keys_by_table.items():
                            display_name = display_by_pair.get((schema, table))
                            if display_name is None:
                                continue
                            keys = [column for _sequence, column in sorted(ordered, key=lambda pair: pair[0])]
                            if keys:
                                result[display_name] = keys
                    except Exception as e:
                        structlog.get_logger().warning(
                            "Failed to detect primary keys for Snowflake schema",
                            schema=schema,
                            exc_info=e,
                        )
                        continue
        except Exception as e:
            structlog.get_logger().warning("Failed to detect primary keys for Snowflake schemas", exc_info=e)

        return result

    def get_leading_index_columns(
        self,
        conn: snowflake.connector.SnowflakeConnection,
        config: SnowflakeSourceConfig,
        tables: list[str],
    ) -> dict[str, set[str]] | None:
        """Return the leading column of the clustering key per table.

        Snowflake doesn't have B-tree indexes; clustering keys are the
        structure that enables partition pruning for `WHERE col >= …`
        predicates. Tables without a clustering key map to an empty set
        so the UI warning fires. Returns None when discovery fails so
        the caller defaults to no warning.
        """
        if not tables:
            return {}

        display_by_pair = _display_by_pair(tables, normalize_namespace(config.schema))
        result: dict[str, set[str]] = {display_name: set() for display_name in tables}
        if not display_by_pair:
            return result

        # Match exact (schema, table) pairs — independent IN clauses over schemas and table
        # names would cross-product and also fetch every same-named table in other schemas.
        pairs = sorted(display_by_pair)

        try:
            with conn.cursor() as cursor:
                if cursor is None:
                    raise Exception("Can't create cursor to Snowflake")

                pair_predicate = " OR ".join(["(TABLE_SCHEMA = %s AND TABLE_NAME = %s)"] * len(pairs))
                cursor.execute(
                    f"""
                    SELECT TABLE_SCHEMA, TABLE_NAME, CLUSTERING_KEY
                    FROM INFORMATION_SCHEMA.TABLES
                    WHERE TABLE_CATALOG = %s
                      AND ({pair_predicate})
                    """,
                    (config.database, *(value for pair in pairs for value in pair)),
                )

                for table_schema, table_name, clustering_key in cursor:
                    display_name = display_by_pair.get((table_schema, table_name))
                    if display_name is None:
                        continue
                    leading = _parse_clustering_key_leading_column(clustering_key)
                    if leading is not None:
                        result[display_name].add(leading)
        except Exception as e:
            structlog.get_logger().warning("Failed to detect clustering keys for Snowflake schemas", exc_info=e)
            return None

        return result

    def get_source_metadata(
        self,
        conn: snowflake.connector.SnowflakeConnection,
        config: SnowflakeSourceConfig,
        tables: list[str],
    ) -> SourceMetadata:
        """Stamp catalog/schema/table per discovered table so per-row routing can pin a namespace.

        The catalog is the connection's database (constant, display-only); the
        schema and unqualified table come from the `schema.table` display name,
        falling back to the configured schema for a single-schema source.
        """
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
        return filter_snowflake_incremental_fields

    # ------------------------------------------------------------------
    # Per-cursor metadata — used during `build_pipeline`
    # ------------------------------------------------------------------

    def get_primary_keys_for_table(
        self,
        cursor: Any,
        database: str,
        schema: str,
        table_name: str,
    ) -> list[str] | None:
        """Return the primary-key column names for a single table, or None.

        Snowflake's `SHOW PRIMARY KEYS IN IDENTIFIER(...)` requires the
        fully qualified `database.schema.table` reference, so this method
        takes `database` in addition to schema/table_name — the only
        driver to do so.
        """
        cursor.execute("SHOW PRIMARY KEYS IN IDENTIFIER(%s)", (f"{database}.{schema}.{table_name}",))

        column_index = next((i for i, row in enumerate(cursor.description) if row.name == "column_name"), -1)

        if column_index == -1:
            raise ValueError("column_name not found in Snowflake cursor description")

        keys = [row[column_index] for row in cursor]

        return keys if len(keys) > 0 else None

    def get_rows_to_sync(
        self,
        cursor: Any,
        inner_query: str,
        inner_query_args: tuple[Any, ...],
        logger: FilteringBoundLogger,
    ) -> int:
        """Count the rows the given `inner_query` will produce. Returns 0 on error."""
        try:
            query = f"SELECT COUNT(*) FROM ({inner_query}) as t"

            cursor.execute(query, inner_query_args)
            row = cursor.fetchone()

            if row is None:
                logger.debug("get_rows_to_sync: No results returned. Using 0 as rows to sync")
                return 0

            rows_to_sync = row[0] or 0
            rows_to_sync_int = int(rows_to_sync)

            logger.debug(f"get_rows_to_sync: rows_to_sync_int={rows_to_sync_int}")
            return rows_to_sync_int
        except Exception as e:
            logger.debug(f"get_rows_to_sync: Error: {e}. Using 0 as rows to sync", exc_info=e)
            capture_exception(e)
            return 0

    # ------------------------------------------------------------------
    # Pipeline build — the dlt `SourceResponse` for a single table
    # ------------------------------------------------------------------

    def build_pipeline(self, config: SnowflakeSourceConfig, inputs: SourceInputs) -> SourceResponse:
        # Per-row routing: a multi-schema row pins its own namespace via `schema_metadata`,
        # a legacy single-schema row falls back to `config.schema`. The database is fixed
        # per connection. `response_name` preserves the legacy Delta subdir (`dwh_storage_key`).
        location = resolve_source_location(inputs, config_namespace=config.schema)
        table_name = location.table_name
        schema = location.schema
        if not table_name:
            raise ValueError("Table name is missing")
        if not schema:
            raise ValueError("Schema is missing")

        database = config.database
        logger = inputs.logger
        should_use_incremental_field = inputs.should_use_incremental_field
        incremental_field = inputs.incremental_field
        incremental_field_type = inputs.incremental_field_type
        db_incremental_field_last_value = inputs.db_incremental_field_last_value
        enabled_columns = inputs.enabled_columns
        row_filters = inputs.row_filters

        with self.connect(config) as connection:
            with connection.cursor() as cursor:
                if cursor is None:
                    raise Exception("Can't create cursor to Snowflake")
                primary_keys = self.get_primary_keys_for_table(cursor, database, schema, table_name)
                inner_query, inner_query_params = _build_query(
                    database,
                    schema,
                    table_name,
                    should_use_incremental_field,
                    incremental_field,
                    incremental_field_type,
                    db_incremental_field_last_value,
                    enabled_columns=enabled_columns,
                    primary_keys=primary_keys,
                    row_filters=row_filters,
                )
                rows_to_sync = self.get_rows_to_sync(cursor, inner_query, inner_query_params, logger)

        def get_rows() -> Iterator[Any]:
            with self.connect(config) as streaming_connection:
                with streaming_connection.cursor() as streaming_cursor:
                    if streaming_cursor is None:
                        raise Exception("Can't create cursor to Snowflake")
                    query, params = _build_query(
                        database,
                        schema,
                        table_name,
                        should_use_incremental_field,
                        incremental_field,
                        incremental_field_type,
                        db_incremental_field_last_value,
                        enabled_columns=enabled_columns,
                        primary_keys=primary_keys,
                        row_filters=row_filters,
                    )
                    logger.debug(f"Snowflake query: {query.format(params)}")
                    streaming_cursor.execute(query, params)

                    # We cant control the batch size from snowflake when using the arrow function
                    # https://github.com/snowflakedb/snowflake-connector-python/issues/1712
                    #
                    # Force microsecond precision so every batch shares one timestamp unit.
                    # Otherwise the connector picks the unit per batch from the data — `ns` for
                    # values in the nanosecond range (~1677–2262) and `us` for anything outside it
                    # (e.g. a `0001-01-01`/`9999-12-31` sentinel) — and the mixed units make
                    # pyarrow fail to assemble the batches ("Schema at index N was different").
                    # The pipeline normalizes timestamps to `us` downstream regardless.
                    yield from streaming_cursor.fetch_arrow_batches(force_microsecond_precision=True)

        return SourceResponse(
            name=location.response_name, items=get_rows, primary_keys=primary_keys, rows_to_sync=rows_to_sync
        )
