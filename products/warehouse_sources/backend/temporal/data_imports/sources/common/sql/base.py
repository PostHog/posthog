"""`SQLSource` template for SQL-based data-import sources.

Every SQL source decomposes into two concerns:

- A PostHog-layer wrapper (config schema, credentials validation,
  error-to-message mapping, registry registration). That's *this* class.
- A driver-layer implementation (connection lifecycle, metadata
  queries, dlt pipeline build). That's `SQLSourceImplementation`, held
  by every `SQLSource` subclass via the `get_implementation` property.

The wrapper stays thin: `get_schemas` opens a connection once via
`impl.connect(config)`, threads it through each query method, and
assembles `SourceSchema` rows; `source_for_pipeline` delegates straight
to `impl.build_pipeline`. Subclasses usually only define:

    get_implementation → MyDriverImplementation()
    source_type, get_source_config, validate_credentials

— no driver code bleeds into the source file.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING, Any, Generic

import structlog

from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import ConfigType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.implementation import (
    SQLSourceImplementation,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.incremental import (
    build_incremental_fields,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.metadata import (
    extract_available_column_names,
    sql_schema_metadata,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.projection import prune_enabled_columns

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

log = structlog.get_logger(__name__)


class SQLSource(SimpleSource[ConfigType], Generic[ConfigType]):
    """Base class for SQL-based data-import sources.

    Subclasses expose a `SQLSourceImplementation` via
    `get_implementation`. Everything else on this class is template
    wiring around it.
    """

    supports_column_selection: bool = True

    @property
    @abstractmethod
    def get_implementation(self) -> SQLSourceImplementation[ConfigType, Any, Any]:
        """The driver-layer implementation for this source."""

    @classmethod
    def default_non_retryable_errors(cls) -> dict[str, str | None]:
        """Non-retryable error patterns shared by multiple SQL sources.

        Subclasses opt in by merging this into their own
        `get_non_retryable_errors` return dict, e.g.
        `return {**self.default_non_retryable_errors(), ...}`. The base
        `SQLSource` itself does not call this — every existing source's
        behavior is preserved until it explicitly opts in.

        The two entries here are the ones currently duplicated across
        ≥2 SQL sources today:

        - "Source column type changed" (MySQL, MSSQL, Snowflake,
          BigQuery, Redshift)
        - "Cannot build decimal array from values" (MySQL, MSSQL)
        """
        return {
            "Source column type changed": (
                "A column's type changed in your source database (for example an integer column was widened to bigint) "
                "and no longer fits the type we stored. We can't widen an existing column in place — please reset and "
                "fully re-sync this table to adopt the new type."
            ),
            "Cannot build decimal array from values": (
                "One of your numeric columns contains values that exceed our decimal storage limits "
                "(max precision 76, max scale 32). Please constrain the column with a lower precision/scale, "
                "cast it to text in a view, or round the values at the source."
            ),
        }

    def _default_primary_key_from_columns(self, columns: list[tuple[str, str, bool]]) -> list[str] | None:
        """Fallback: use `id` when the driver didn't detect a PK but one is present.

        Mirrors what every SQL source has always done just before building
        a `SourceSchema`.
        """
        if any(col[0] == "id" for col in columns):
            return ["id"]
        return None

    def get_schemas(
        self,
        config: ConfigType,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        impl = self.get_implementation
        with impl.connect(config) as conn:
            columns_by_table = impl.get_columns(conn, config, names)
            if not columns_by_table:
                return []
            tables = list(columns_by_table.keys())
            primary_keys = impl.get_primary_keys(conn, config, tables)
            row_counts = impl.get_row_counts(conn, config, tables) if with_counts else {}
            foreign_keys = impl.get_foreign_keys(conn, config, tables)
            metadata = impl.get_source_metadata(conn, config, tables)
            cdc_support = impl.get_cdc_support(conn, config, tables)
            indexed_columns_by_table = impl.get_leading_index_columns(conn, config, tables)

        incremental_filter = impl.get_incremental_filter()

        schemas: list[SourceSchema] = []
        for table_name, columns in columns_by_table.items():
            incremental_triples = incremental_filter(columns)
            detected_pks = primary_keys.get(table_name) or self._default_primary_key_from_columns(columns)
            indexed_columns = indexed_columns_by_table.get(table_name) if indexed_columns_by_table is not None else None

            schemas.append(
                SourceSchema(
                    name=table_name,
                    supports_incremental=len(incremental_triples) > 0,
                    supports_append=len(incremental_triples) > 0,
                    supports_cdc=cdc_support.get(table_name, False),
                    incremental_fields=build_incremental_fields(incremental_triples, indexed_columns),
                    columns=columns,
                    row_count=row_counts.get(table_name),
                    foreign_keys=foreign_keys.get(table_name, []),
                    source_catalog=metadata.catalog_by_table.get(table_name),
                    source_schema=metadata.schema_by_table.get(table_name),
                    source_table_name=metadata.table_name_by_table.get(table_name),
                    detected_primary_keys=detected_pks,
                )
            )
        return schemas

    def source_for_pipeline(self, config: ConfigType, inputs: SourceInputs) -> SourceResponse:
        return self.get_implementation.build_pipeline(config, inputs)

    def reconcile_schema_metadata(
        self,
        source: ExternalDataSource,
        source_schemas: list[SourceSchema],
        team_id: int,
    ) -> list[str]:
        """Persist `schema_metadata` per row and prune stale `enabled_columns`.

        Returns schema names this hook soft-deleted (default impl never does;
        override to handle direct-query table cleanup).
        """
        return reconcile_source_schema_metadata(source, source_schemas, team_id)


def reconcile_source_schema_metadata(
    source: ExternalDataSource,
    source_schemas: list[SourceSchema],
    team_id: int,
) -> list[str]:
    """Persist `schema_metadata` per schema row and prune stale `enabled_columns`.

    Generic over the source driver — it reads only `SourceSchema` fields and the
    `ExternalDataSchema` rows — so non-`SQLSource` sources (e.g. ClickHouse) can
    reuse it to surface column metadata for row filters and the column picker.
    Returns schema names soft-deleted by this hook (currently none).
    """
    schemas_by_name: dict[str, SourceSchema] = {s.name: s for s in source_schemas}
    rows = ExternalDataSchema.objects.filter(team_id=team_id, source_id=source.id, deleted=False)
    for row in rows:
        source_schema = schemas_by_name.get(row.name)
        if source_schema is None:
            continue
        new_metadata = sql_schema_metadata(
            source_schema.columns,
            source_schema.foreign_keys,
            source_catalog=source_schema.source_catalog,
            source_schema=source_schema.source_schema,
            source_table_name=source_schema.source_table_name,
        )
        existing_config: dict[str, Any] = dict(row.sync_type_config) if isinstance(row.sync_type_config, dict) else {}
        existing_config["schema_metadata"] = new_metadata

        available_names = extract_available_column_names(new_metadata)
        pruned_enabled_columns, removed_columns = prune_enabled_columns(row.enabled_columns, available_names)
        update_fields = ["sync_type_config", "updated_at"]
        if removed_columns:
            log.info(
                "sql_source.reconcile_schema_metadata.pruned_enabled_columns",
                source_id=str(source.id),
                schema_id=str(row.id),
                schema_name=row.name,
                removed_columns=removed_columns,
            )
            row.enabled_columns = pruned_enabled_columns
            update_fields.append("enabled_columns")

        row.sync_type_config = existing_config
        row.save(update_fields=update_fields)

    return []
