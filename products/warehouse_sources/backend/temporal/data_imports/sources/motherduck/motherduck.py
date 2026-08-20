"""MotherDuck driver for PostHog's data-warehouse import pipeline.

MotherDuck is DuckDB served from the cloud, so the client is the ordinary
`duckdb` package pointed at an `md:<database>` connection string carrying a
MotherDuck access token. Everything MotherDuck-specific — connection string
assembly, `information_schema` discovery, and the pipeline build — lives on
`MotherDuckImplementation`. The source-class `MotherduckSource` is a thin
PostHog-layer wrapper that holds an instance and validates credentials.

The database name is optional. Left blank, the connection is account-wide
(`md:`) and discovery spans every catalog the token can see, qualifying tables
as `catalog.schema.table`; set, the connection pins that one catalog and tables
stay `schema.table`. Either way a query runs against exactly one catalog: the
pipeline issues `USE "<catalog>"` before it reads, so every catalog-scoped
discovery query stays written against `current_database()`.

DuckDB runs in-process inside the Temporal worker, so this driver bounds both
what DuckDB may allocate (`DUCKDB_LOCAL_CONFIG`) and how many rows it
materializes at once (an Arrow record-batch reader rather than a full fetch).
"""

from __future__ import annotations

import os
import re
import tempfile
import collections
import dataclasses
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
    ResolvedSourceLocation,
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
    "MotherDuckConnectionError",
    "MotherDuckImplementation",
    "build_motherduck_connection_string",
    "connect",
    "filter_motherduck_incremental_fields",
    "translate_motherduck_error",
]

_IDENTIFIER_QUOTER = AnsiIdentifierQuoter()

# DuckDB binds `?` placeholders positionally from a list.
_QUERY_BUILDER = SelectQueryBuilder(quoter=_IDENTIFIER_QUOTER, param_style=ParamStyle.QMARK)

# MotherDuck is a single global service — there is no per-account hostname to configure.
MOTHERDUCK_SERVICE_HOST = "api.motherduck.com"

# DuckDB's catalog metadata schemas. `main` is a real user schema in DuckDB, not a system one.
MOTHERDUCK_SYSTEM_SCHEMAS = ("information_schema", "pg_catalog")

# Catalogs MotherDuck and the client attach for their own bookkeeping — never user data. Only
# consulted for an account-wide connection; pinning a database scopes discovery on its own.
MOTHERDUCK_SYSTEM_DATABASES = ("md_information_schema", "system", "temp", "memory", "_duckdb_ui")

# DuckDB prefixes every error message with its stable error class ("Catalog Error:", "Binder
# Error:", …). The text after the prefix carries volatile object names, so we match the class.
MOTHERDUCK_ERROR_CLASSES = {
    "Catalog Error": "Can't find that database or schema in MotherDuck. Check the database and schema names, then try again.",
    "Binder Error": "MotherDuck rejected the query. Check that the database and schema still contain the tables you want to sync.",
    "Invalid Input Error": "MotherDuck rejected the connection details. Check the database name and access token, then try again.",
}

# Rows materialized per Arrow batch. Bounds resident memory: DuckDB shares this process.
DEFAULT_MOTHERDUCK_FETCH_SIZE = 5_000

_DUCKDB_HOME = os.path.join(tempfile.gettempdir(), "posthog-duckdb-home")

# DuckDB otherwise sizes itself against the whole host, the wrong budget for a library sharing this
# worker. `extension_directory` needs its own override: `home_directory` doesn't move it, so
# extension autoload would try to create the unwritable `~/.duckdb` in the worker.
DUCKDB_LOCAL_CONFIG: dict[str, Any] = {
    "memory_limit": "2GB",
    "threads": 2,
    "home_directory": _DUCKDB_HOME,
    "extension_directory": os.path.join(_DUCKDB_HOME, "extensions"),
}

# The database name is interpolated into the `md:` connection string, so anything outside this
# allowlist could smuggle extra connection parameters in alongside the token.
_VALID_DATABASE_NAME = re.compile(r"^[A-Za-z0-9_.\-$]+$")


class MotherDuckConnectionError(Exception):
    """A MotherDuck connection could not be opened, carrying a user-facing message."""


def build_motherduck_connection_string(database: Optional[str], access_token: str) -> str:
    """Assemble the `md:[<database>]?motherduck_token=…` DSN duckdb expects.

    A blank database yields the account-wide `md:` form, which attaches every database
    the token can see. Raises `ValueError` for a missing token or a database name that
    could alter the DSN's query string. Never log the return value: it carries the token.
    """
    name = (database or "").strip()
    if name and not _VALID_DATABASE_NAME.match(name):
        raise ValueError(f"Invalid MotherDuck database name: {name!r}")
    if not access_token:
        raise ValueError("Access token is missing")
    # `saas_mode` denies local filesystem access and extension installs. DuckDB runs in-process
    # here, so without it a query could read the worker's disk.
    params = urlencode({"motherduck_token": access_token, "saas_mode": "true"})
    return f"md:{name}?{params}"


def connect(access_token: str, database: Optional[str] = None, *, read_only: bool = True) -> duckdb.DuckDBPyConnection:
    """Open a MotherDuck connection, translating driver errors to `MotherDuckConnectionError`.

    Read-only by default: neither imports nor direct queries write, so DuckDB rejects every
    write statement engine-side regardless of what the token is granted.
    """
    connection_string = build_motherduck_connection_string(database, access_token)
    config = dict(DUCKDB_LOCAL_CONFIG)
    # Extension autoload runs as the connection opens, so the store has to exist by then. Creating
    # it also creates the home directory above it.
    os.makedirs(config["extension_directory"], exist_ok=True)
    log_connection_open(db_host=MOTHERDUCK_SERVICE_HOST, via="vendor_https")
    try:
        return duckdb.connect(connection_string, read_only=read_only, config=config)
    except duckdb.Error as e:
        raise MotherDuckConnectionError(translate_motherduck_error(e)) from e


def translate_motherduck_error(error: Exception) -> str:
    """Turn a driver error into a message we can show the source's owner."""
    message = str(error)
    lowered = message.lower()
    if "unauthenticated" in lowered or "invalid token" in lowered or "jwt" in lowered or "authenticat" in lowered:
        return "Invalid MotherDuck token. Generate a new access token in MotherDuck settings and try again."
    if "database" in lowered and ("not found" in lowered or "does not exist" in lowered):
        return "Database not found. Check the database name, or leave it blank to connect to all databases."
    if "compute limit" in lowered or "out of compute" in lowered:
        return (
            "Your MotherDuck plan has reached its compute limit. Queries may be slow or fail until the "
            "limit resets. Upgrade your MotherDuck plan for more capacity."
        )
    for key, value in MOTHERDUCK_ERROR_CLASSES.items():
        if key in message:
            return value
    # First line only: DuckDB appends multi-line candidate/hint blocks.
    return message.splitlines()[0] if message.strip() else "Could not connect to MotherDuck."


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


def _default_catalog(config: MotherduckSourceConfig) -> Optional[str]:
    """The catalog every table belongs to, or None when the source spans the account."""
    return (config.database or "").strip() or None


def _name_suffixes(name: str) -> list[str]:
    """Progressively less-qualified forms of a dotted name, most qualified first.

    `a.b.c` yields `b.c` then `c`, so a stored name can still be matched against a
    discovery key that carries fewer qualifiers than it did when the row was created.
    """
    parts = name.split(".")
    return [".".join(parts[i:]) for i in range(1, len(parts))]


def _split_display_name(
    display_name: str,
    default_catalog: Optional[str],
    default_schema: Optional[str],
) -> tuple[Optional[str], Optional[str], str]:
    """Split a discovery display name into `(catalog, schema, table)`.

    Discovery qualifies a name with exactly the parts the config leaves open: an
    account-wide source gets `catalog.schema.table`, a pinned database `schema.table`,
    and a pinned database and schema a bare `table`. The dotted form mirrors
    `resolve_source_location`'s self-heal so listing keys and per-row routing agree.
    """
    parts = display_name.split(".", 2)
    if len(parts) == 3:
        catalog, schema, table = parts
        return (
            normalize_namespace(catalog) or default_catalog,
            normalize_namespace(schema) or default_schema,
            table,
        )
    if len(parts) == 2:
        schema, table = parts
        return default_catalog, (normalize_namespace(schema) or default_schema), table
    return default_catalog, default_schema, display_name


class MotherDuckImplementation(SQLSourceImplementation[MotherduckSourceConfig, Any, Any]):
    """MotherDuck driver implementation paired with `MotherduckSource`.

    Discovery reads DuckDB's `information_schema` and its `duckdb_constraints()` /
    `duckdb_tables()` catalog functions. With a database pinned they stay scoped to
    `current_database()`, so the client's own `memory`, `system` and `temp` catalogs
    never surface as tables; account-wide they span every catalog except those.

    Partition sizing is deliberately not implemented: DuckDB's catalog exposes an
    estimated row count but no on-disk byte size for an attached MotherDuck
    database, and the shared partition math needs bytes. The base class returns
    `None`, which falls back to default partition settings.
    """

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    @contextmanager
    def connect(self, config: MotherduckSourceConfig, catalog: Optional[str] = None) -> Iterator[Any]:
        """Open a MotherDuck-backed DuckDB connection for the duration of the context.

        `catalog` pins the connection's current database, so a caller reading one table
        out of an account-wide source can keep using `current_database()`-scoped SQL.
        """
        connection = connect(config.access_token, config.database)
        try:
            # A pinned database is already the connection's current catalog, so switching is
            # only needed when an account-wide source reaches into a specific one.
            if catalog and catalog != _default_catalog(config):
                connection.execute(f"USE {_IDENTIFIER_QUOTER.quote(catalog)}")
            yield connection
        finally:
            connection.close()

    def _catalog_predicate(self, config: MotherduckSourceConfig, column: str) -> tuple[str, list[str]]:
        """Restrict a catalog-metadata query to the catalogs this source may read.

        A pinned database narrows to `current_database()`; account-wide, every catalog
        is in scope except MotherDuck's and the client's own bookkeeping ones.
        """
        if (config.database or "").strip():
            return f"{column} = current_database()", []
        placeholders = ", ".join("?" for _ in MOTHERDUCK_SYSTEM_DATABASES)
        return f"{column} NOT IN ({placeholders})", list(MOTHERDUCK_SYSTEM_DATABASES)

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
        qualify_schema = selected_schema is None
        qualify_catalog = not (config.database or "").strip()
        catalog_clause, catalog_params = self._catalog_predicate(config, "c.table_catalog")

        # Joined against `information_schema.tables` and restricted to `BASE TABLE`: a view's
        # columns are otherwise indistinguishable here from a real table's, but its definition
        # runs inside this Temporal worker at query time. A source owner could define a view over
        # a locally-executed DuckDB table function (e.g. reading the worker's filesystem) and have
        # it synced like any other table, so views are never offered for discovery.
        select = (
            "SELECT c.table_catalog, c.table_schema, c.table_name, c.column_name, c.data_type, c.is_nullable"
            " FROM information_schema.columns c"
            " JOIN information_schema.tables t"
            "   ON t.table_catalog = c.table_catalog"
            "  AND t.table_schema = c.table_schema"
            "  AND t.table_name = c.table_name"
            f" WHERE {catalog_clause}"
            "   AND t.table_type = 'BASE TABLE'"
        )
        order = " ORDER BY c.table_catalog ASC, c.table_schema ASC, c.table_name ASC, c.ordinal_position ASC"

        if selected_schema is not None:
            result = conn.execute(
                f"{select} AND c.table_schema = ?{order}", [*catalog_params, selected_schema]
            ).fetchall()
        else:
            placeholders = ", ".join("?" for _ in MOTHERDUCK_SYSTEM_SCHEMAS)
            result = conn.execute(
                f"{select} AND c.table_schema NOT IN ({placeholders}){order}",
                [*catalog_params, *MOTHERDUCK_SYSTEM_SCHEMAS],
            ).fetchall()

        schema_list: dict[str, list[tuple[str, str, bool]]] = collections.defaultdict(list)
        for table_catalog, table_schema, table_name, column_name, data_type, is_nullable in result:
            display_name = table_name
            if qualify_schema:
                display_name = f"{table_schema}.{display_name}"
            if qualify_catalog:
                display_name = f"{table_catalog}.{display_name}"
            schema_list[display_name].append((column_name, data_type, is_nullable == "YES"))

        if names is not None:
            # Match qualified (`[catalog.]schema.table`) and less-qualified names — a row requested
            # by its qualified name can still map to a barer discovery key (or vice versa)
            # mid-migration, e.g. after a source gains or drops its pinned database.
            available = dict(schema_list)
            filtered: dict[str, list[tuple[str, str, bool]]] = {}
            for name in names:
                if name in available:
                    filtered[name] = available[name]
                    continue
                for suffix in _name_suffixes(name):
                    if suffix in available:
                        filtered[name] = available[suffix]
                        break
            return filtered

        return dict(schema_list)

    def _display_names_by_location(
        self,
        config: MotherduckSourceConfig,
        tables: list[str],
    ) -> dict[tuple[Optional[str], str, str], str]:
        """Index the requested display names by their `(catalog, schema, table)` triple.

        The catalog is left `None` when the source pins a database, because the catalog
        functions are then already restricted to it and don't need to disambiguate.
        """
        default_catalog = _default_catalog(config)
        default_schema = normalize_namespace(config.schema)
        # Only an account-wide source sees more than one catalog, so only it needs the catalog
        # to tell two same-named tables apart.
        key_by_catalog = default_catalog is None
        locations: dict[tuple[Optional[str], str, str], str] = {}
        for display_name in tables:
            catalog, schema, table = _split_display_name(display_name, default_catalog, default_schema)
            if schema is None:
                continue
            locations[(catalog if key_by_catalog else None, schema, table)] = display_name
        return locations

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

        display_by_location = self._display_names_by_location(config, tables)
        key_by_catalog = _default_catalog(config) is None
        catalog_clause, catalog_params = self._catalog_predicate(config, "database_name")

        try:
            rows = conn.execute(
                "SELECT database_name, schema_name, table_name, constraint_column_names"
                " FROM duckdb_constraints()"
                f" WHERE {catalog_clause} AND constraint_type = 'PRIMARY KEY'",
                catalog_params,
            ).fetchall()
        except Exception as e:
            structlog.get_logger().warning("Failed to detect primary keys for MotherDuck tables", exc_info=e)
            return result

        for database_name, schema_name, table_name, columns in rows:
            display_key = display_by_location.get((database_name if key_by_catalog else None, schema_name, table_name))
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

        display_by_location = self._display_names_by_location(config, tables)
        key_by_catalog = _default_catalog(config) is None
        catalog_clause, catalog_params = self._catalog_predicate(config, "database_name")

        try:
            rows = conn.execute(
                "SELECT database_name, schema_name, table_name, estimated_size"
                " FROM duckdb_tables()"
                f" WHERE {catalog_clause}",
                catalog_params,
            ).fetchall()
        except Exception as e:
            structlog.get_logger().warning("Failed to read row counts for MotherDuck tables", exc_info=e)
            return result

        for database_name, schema_name, table_name, estimated_size in rows:
            display_key = display_by_location.get((database_name if key_by_catalog else None, schema_name, table_name))
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
        default_catalog = _default_catalog(config)
        default_schema = normalize_namespace(config.schema)
        catalog_by_table: dict[str, str | None] = {}
        schema_by_table: dict[str, str | None] = {}
        table_name_by_table: dict[str, str | None] = {}
        for display_name in tables:
            catalog, schema, table = _split_display_name(display_name, default_catalog, default_schema)
            catalog_by_table[display_name] = catalog
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

    def _resolve_location(
        self, config: MotherduckSourceConfig, inputs: SourceInputs
    ) -> tuple[Optional[str], ResolvedSourceLocation]:
        """Resolve `(catalog, location)` for one row.

        The shared resolver splits a dotted name on its first dot, so it would read the
        catalog of a three-part `catalog.schema.table` as the schema. The prefix is removed
        before delegating, then `response_name` is taken from the untouched name so the Delta
        folder stays unique across two catalogs holding the same `schema.table`.
        """
        metadata = inputs.schema_metadata if isinstance(inputs.schema_metadata, dict) else {}
        source_catalog = metadata.get("source_catalog")
        catalog = source_catalog if isinstance(source_catalog, str) and source_catalog else None

        has_location = bool(metadata.get("source_schema")) and bool(metadata.get("source_table_name"))
        resolver_inputs = inputs
        if not has_location and inputs.schema_name.count(".") == 2:
            prefix, _, remainder = inputs.schema_name.partition(".")
            catalog = catalog or normalize_namespace(prefix)
            resolver_inputs = dataclasses.replace(inputs, schema_name=remainder)

        location = resolve_source_location(resolver_inputs, config_namespace=config.schema)
        if resolver_inputs is not inputs:
            location = location._replace(
                response_name=resolve_source_location(inputs, config_namespace=config.schema).response_name
            )
        return catalog or _default_catalog(config), location

    def build_pipeline(self, config: MotherduckSourceConfig, inputs: SourceInputs) -> SourceResponse:
        # Per-row routing: a row pins its own namespace via `schema_metadata`, falling back to
        # `config.schema` and the source's database. An account-wide source reaches several
        # catalogs, so the catalog is per row too and the connection is pinned to it below.
        catalog, location = self._resolve_location(config, inputs)
        table_name = location.table_name
        schema = location.schema
        if not table_name:
            raise ValueError("Table name is missing")
        if not schema:
            raise ValueError("Schema is missing")
        if not catalog:
            raise ValueError(f"Could not resolve the MotherDuck database for table '{inputs.schema_name}'")

        logger = inputs.logger
        incremental_field = inputs.incremental_field if inputs.should_use_incremental_field else None
        incremental_field_type = inputs.incremental_field_type if inputs.should_use_incremental_field else None

        with self.connect(config, catalog=catalog) as connection:
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
            with self.connect(config, catalog=catalog) as streaming_connection:
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
