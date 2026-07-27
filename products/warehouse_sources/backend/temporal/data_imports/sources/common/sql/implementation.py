"""Driver-side composition object for SQL sources.

`SQLSourceImplementation` is the contract every SQL driver implements.
It owns the *driver-shaped* parts of the source — connection lifecycle,
`information_schema`-style metadata queries, per-cursor streaming
metadata, and the dlt pipeline build — so that `SQLSource` (the
PostHog-layer wrapper) stays a thin template over the driver.

One implementation per driver, per-instance stateless: each public
method takes the `config` it needs. `SQLSource.get_schemas` opens the
connection once via `connect(config)` and threads the resulting
connection through every query method — giving every driver the
"single-tunnel-per-listing" behavior without each source having to
orchestrate it themselves.

Required methods: `connect`, `get_columns`, `get_incremental_filter`,
`build_pipeline`. Optional listing methods (`get_primary_keys`,
`get_row_counts`, …) return empty by default. Optional streaming
methods (`fetch_table_stats`, `fetch_average_row_size`) return `None`
by default so a driver opts into partition/chunk sizing by overriding
them — the base class does the math (`get_partition_settings`,
`get_chunk_size`) on top of those two hooks.
"""

from __future__ import annotations

import math
import dataclasses
from abc import ABC, abstractmethod
from contextlib import AbstractContextManager
from typing import Any, Generic, Protocol, TypeVar

from structlog.types import FilteringBoundLogger

from posthog.exceptions_capture import capture_exception

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.consts import (
    DEFAULT_CHUNK_SIZE,
    DEFAULT_TABLE_SIZE_BYTES,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.utils import (
    DEFAULT_PARTITION_TARGET_SIZE_IN_BYTES,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.config import Config
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.incremental import (
    IncrementalFieldFilter,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.types import Column, Table
from products.warehouse_sources.backend.types import PartitionSettings


class _CursorLike(Protocol):
    """The bare minimum surface the shared math uses on a DB-API cursor.

    Narrow Protocol (instead of typing against `pymysql.cursors.Cursor`,
    `psycopg.Cursor`, etc.) so the base class stays driver-agnostic.
    Concrete implementations are `Generic[CursorT]` and can tighten this
    to their real cursor type.
    """

    def execute(self, query: str, args: Any = ...) -> Any: ...
    def fetchone(self) -> Any: ...
    def fetchall(self) -> Any: ...


ConfigT = TypeVar("ConfigT", bound=Config)
ConnT = TypeVar("ConnT")
CursorT = TypeVar("CursorT", bound=_CursorLike)


@dataclasses.dataclass(frozen=True)
class TableStats:
    """Table-level statistics used to compute partition settings.

    Populated from driver-specific metadata tables — `information_schema.TABLES`
    on MySQL, `pg_class` on Postgres, etc. Both values are estimates:
    nothing downstream needs them to be exact, they just need to be close
    enough to pick a reasonable partition size.
    """

    table_size_bytes: int
    row_count: int


@dataclasses.dataclass
class SourceMetadata:
    """Per-table catalog / schema / table-name overrides.

    Sources that distinguish catalog (project/account) from schema
    (database/dataset) from table (logical name) populate these
    dictionaries; most SQL sources leave them empty and let the base
    derive identity from the config.
    """

    catalog_by_table: dict[str, str | None] = dataclasses.field(default_factory=dict)
    schema_by_table: dict[str, str | None] = dataclasses.field(default_factory=dict)
    table_name_by_table: dict[str, str | None] = dataclasses.field(default_factory=dict)


class SQLSourceImplementation(Generic[ConfigT, ConnT, CursorT], ABC):
    """Driver-side contract paired with `SQLSource`.

    `ConfigT` is the driver's typed config class (e.g.
    `MySQLSourceConfig`). `ConnT` is whatever the driver's native
    connection object is (`pymysql.Connection`, `psycopg.Connection`,
    `snowflake.connector.SnowflakeConnection`, a REST client, …).
    `CursorT` is the cursor type returned by `conn.cursor()` — used by
    the shared partition/chunk sizing math.
    """

    # ------------------------------------------------------------------
    # Required
    # ------------------------------------------------------------------

    @abstractmethod
    def connect(self, config: ConfigT) -> AbstractContextManager[ConnT]:
        """Open a driver connection for the duration of schema discovery.

        Implementations own the full lifecycle — SSH tunnel (if any),
        TLS, auth, cursor setup — and clean it up on exit.
        """

    @abstractmethod
    def get_columns(
        self,
        conn: ConnT,
        config: ConfigT,
        names: list[str] | None,
    ) -> dict[str, list[tuple[str, str, bool]]]:
        """Return `{table_name: [(column_name, data_type, nullable), …]}`.

        `names` scopes the listing; `None` means "every table visible in
        this schema/database".
        """

    @abstractmethod
    def get_incremental_filter(self) -> IncrementalFieldFilter:
        """Map driver column-type strings onto `IncrementalFieldType`s."""

    @abstractmethod
    def build_pipeline(self, config: ConfigT, inputs: SourceInputs) -> SourceResponse:
        """Construct the dlt `SourceResponse` for a single schema sync."""

    # ------------------------------------------------------------------
    # Optional listing queries — base returns empty so drivers opt in
    # ------------------------------------------------------------------

    def get_primary_keys(
        self,
        conn: ConnT,
        config: ConfigT,
        tables: list[str],
    ) -> dict[str, list[str] | None]:
        return {}

    def get_row_counts(
        self,
        conn: ConnT,
        config: ConfigT,
        tables: list[str],
    ) -> dict[str, int | None]:
        return {}

    def get_foreign_keys(
        self,
        conn: ConnT,
        config: ConfigT,
        tables: list[str],
    ) -> dict[str, list[tuple[str, str, str]]]:
        return {}

    def get_source_metadata(
        self,
        conn: ConnT,
        config: ConfigT,
        tables: list[str],
    ) -> SourceMetadata:
        return SourceMetadata()

    def get_cdc_support(
        self,
        conn: ConnT,
        config: ConfigT,
        tables: list[str],
    ) -> dict[str, bool]:
        return {}

    def get_leading_index_columns(
        self,
        conn: ConnT,
        config: ConfigT,
        tables: list[str],
    ) -> dict[str, set[str]] | None:
        """Return `{table_name: {leading_index_column, …}}` per table, or `None`.

        Drives the UI warning when a user picks an incremental field with
        no index on the source. Returning `None` means "lookup failed —
        don't warn, treat every field as indexed". Tables present with an
        empty set mean "we looked, no indexes here — warn for every
        candidate". Drivers opt in by overriding; the default skips the
        feature (every field reported as indexed).
        """
        return None

    # ------------------------------------------------------------------
    # Optional streaming queries — called from within `build_pipeline`
    # on a live cursor. Base returns `None` so drivers opt into partition
    # and chunk sizing by overriding.
    # ------------------------------------------------------------------

    def get_table_metadata(
        self,
        cursor: CursorT,
        schema: str,
        table_name: str,
    ) -> Table[Column] | None:
        """Return rich column metadata for building a PyArrow schema.

        Drivers override with a narrower return (`Table[<driver>Column]`)
        — every SQL source has this concept (the Arrow schema fed to
        dlt). Covariance on `Table`'s `ColumnType` makes the narrower
        override LSP-compliant.
        """
        return None

    def fetch_table_stats(
        self,
        cursor: CursorT,
        schema: str,
        table_name: str,
        logger: FilteringBoundLogger,
    ) -> TableStats | None:
        """Return an estimate of the table's size + row count, or `None`.

        Drivers that want `get_partition_settings` to produce non-None
        must override this — e.g. query `information_schema.TABLES` on
        MySQL or `pg_class` on Postgres.
        """
        return None

    def get_rows_to_sync(
        self,
        cursor: CursorT,
        inner_query: str,
        inner_query_args: Any,
        logger: FilteringBoundLogger,
    ) -> int:
        """Count rows the given `inner_query` will produce. Returns 0 on error.

        Mirrors the shape shared by MySQL, MSSQL, and Snowflake today.
        Drivers can still override — MySQL injects a
        `/*+ MAX_EXECUTION_TIME(60000) */` optimizer hint, for example —
        but the default suits any driver whose `COUNT(*) FROM (...)` is
        not pathologically slow.
        """
        try:
            cursor.execute(f"SELECT COUNT(*) FROM ({inner_query}) as t", inner_query_args)
            row = cursor.fetchone()
            if row is None:
                logger.debug("get_rows_to_sync: No results returned. Using 0 as rows to sync")
                return 0
            rows_to_sync_int = int(row[0] or 0)
            logger.debug(f"get_rows_to_sync: rows_to_sync_int={rows_to_sync_int}")
            return rows_to_sync_int
        except Exception as e:
            logger.debug(f"get_rows_to_sync: Error: {e}. Using 0 as rows to sync", exc_info=e)
            capture_exception(e)
            return 0

    def fetch_average_row_size(
        self,
        cursor: CursorT,
        schema: str,
        table_name: str,
        inner_query: str,
        inner_query_args: Any,
        logger: FilteringBoundLogger,
    ) -> int | None:
        """Return the average row size in bytes sampled from the filtered query.

        Drivers that want `get_chunk_size` to tune the streaming chunk
        size must override this — e.g. `LENGTH(col)` sampling on MySQL,
        `percentile_cont(octet_length(...))` on Postgres.
        """
        return None

    # ------------------------------------------------------------------
    # Shared math — concrete, identical across every SQL driver today
    # ------------------------------------------------------------------

    def get_partition_settings(
        self,
        cursor: CursorT,
        schema: str,
        table_name: str,
        logger: FilteringBoundLogger,
        partition_size_bytes: int = DEFAULT_PARTITION_TARGET_SIZE_IN_BYTES,
    ) -> PartitionSettings | None:
        """Compute `PartitionSettings` from `fetch_table_stats`.

        Returns None when stats are missing or the table is empty; the
        caller decides what to do in that case.
        """
        try:
            stats = self.fetch_table_stats(cursor, schema, table_name, logger)
        except Exception as e:
            # Partition sizing is a best-effort optimization: returning None just falls back to
            # default partition settings and the sync proceeds. Any genuine problem (missing table,
            # permissions) resurfaces in the real extraction query and is classified through the
            # normal retryable/non-retryable path, while transient connection drops here stay
            # retryable there too. Capturing it would only flood error tracking with handled
            # duplicates, so log at debug and fall back.
            logger.debug(f"get_partition_settings: Error fetching stats: {e}. Returning None", exc_info=e)
            return None

        if stats is None or stats.row_count == 0:
            logger.debug("get_partition_settings: no usable stats returning None")
            return None

        avg_row_size = stats.table_size_bytes / stats.row_count
        if avg_row_size <= 0:
            logger.debug("get_partition_settings: non-positive avg_row_size, returning None")
            return None

        # A partition must hold at least one row.
        partition_size = max(round(partition_size_bytes / avg_row_size), 1)
        partition_count = math.floor(stats.row_count / partition_size)

        if partition_count == 0:
            logger.debug(f"get_partition_settings: partition_count == 0, returning partition_size={partition_size}")
            return PartitionSettings(partition_count=1, partition_size=partition_size)

        logger.debug(f"get_partition_settings: partition_count={partition_count}, partition_size={partition_size}")
        return PartitionSettings(partition_count=partition_count, partition_size=partition_size)

    def get_chunk_size(
        self,
        cursor: CursorT,
        schema: str,
        table_name: str,
        inner_query: str,
        inner_query_args: Any,
        logger: FilteringBoundLogger,
        default_chunk_size: int = DEFAULT_CHUNK_SIZE,
        target_chunk_size_bytes: int = DEFAULT_TABLE_SIZE_BYTES,
    ) -> int:
        """Compute a safe `fetchmany` chunk size from the sampled row size.

        Falls back to `default_chunk_size` whenever sampling fails or
        returns a non-positive value — matches what every SQL source
        does today.
        """
        try:
            row_size_bytes = self.fetch_average_row_size(
                cursor, schema, table_name, inner_query, inner_query_args, logger
            )
        except Exception as e:
            logger.debug(
                f"get_chunk_size: Error: {e}. Using default_chunk_size={default_chunk_size}",
                exc_info=e,
            )
            capture_exception(e)
            return default_chunk_size

        if row_size_bytes is None or row_size_bytes <= 0:
            logger.debug(f"get_chunk_size: Could not calculate row size. Using default_chunk_size={default_chunk_size}")
            return default_chunk_size

        # Cap at `default_chunk_size` so narrow rows don't blow up the
        # row count. `target_chunk_size_bytes` bounds memory in *bytes*,
        # but each fetched row becomes a Python dict with its own
        # overhead — an unbounded row count can exceed the byte budget
        # once serialized.
        chunk_size = min(int(target_chunk_size_bytes / row_size_bytes), default_chunk_size)
        chunk_size = max(chunk_size, 1)
        logger.debug(
            f"get_chunk_size: row_size_bytes={row_size_bytes}. "
            f"target_chunk_size_bytes={target_chunk_size_bytes}. Using CHUNK_SIZE={chunk_size}"
        )
        return chunk_size
