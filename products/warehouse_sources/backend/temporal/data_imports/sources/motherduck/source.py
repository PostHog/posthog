from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING, Optional, cast

import duckdb

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from posthog.exceptions_capture import capture_exception

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.base import (
    reconcile_source_schema_metadata,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.motherduck import (
    MotherduckSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.motherduck.motherduck import (
    MotherDuckConnectionError,
    closing_connection,
    filter_motherduck_incremental_fields,
    get_connection_metadata as get_motherduck_connection_metadata,
    get_primary_keys as get_motherduck_primary_keys,
    get_schemas as get_motherduck_schemas,
    motherduck_source,
    translate_motherduck_error,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType, IncrementalField

if TYPE_CHECKING:
    from products.warehouse_sources.backend.models.external_data_source import ExternalDataSource

GENERIC_CONNECTION_ERROR = (
    "Could not connect to MotherDuck. Check that your access token is valid and the database name is correct."
)


@SourceRegistry.register
class MotherduckSource(SimpleSource[MotherduckSourceConfig]):
    api_docs_url = "https://motherduck.com/docs/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MOTHERDUCK

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MOTHERDUCK,
            category=DataWarehouseSourceCategory.DATABASES,
            label="MotherDuck",
            keywords=["duckdb", "md", "sql"],
            releaseStatus=ReleaseStatus.ALPHA,
            caption=(
                "Connect your MotherDuck account with an access token to query or sync your DuckDB "
                "databases. Leave the database blank to connect to every database in the account. "
                "Connections are opened read-only, so PostHog never modifies your data."
            ),
            iconPath="/static/services/motherduck.png",
            docsUrl="https://posthog.com/docs/cdp/sources/motherduck",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="motherduck_token",
                        label="Access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="database",
                        label="Database (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="my_db",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "Invalid MotherDuck token": None,
            "UNAUTHENTICATED": "Your MotherDuck token is invalid or expired. Generate a new access token and reconnect.",
            "Database not found": None,
        }

    @contextmanager
    def direct_query_connection(self, config: MotherduckSourceConfig) -> Iterator[duckdb.DuckDBPyConnection]:
        """Open a read-only connection for a single direct (HogQL) query.

        Connection construction is an internal detail of the source; the direct-SQL adapter
        drives queries through this method rather than importing the driver helpers.
        """
        with closing_connection(config.motherduck_token, self.normalized_database(config)) as connection:
            yield connection

    @staticmethod
    def normalized_database(config: MotherduckSourceConfig) -> str | None:
        database = (config.database or "").strip()
        return database or None

    def get_schemas(
        self,
        config: MotherduckSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        database = self.normalized_database(config)
        discovered = get_motherduck_schemas(
            config.motherduck_token,
            database,
            names=names,
            with_counts=with_counts,
        )

        locations = [(entry["database"], entry["schema"], entry["table"]) for entry in discovered.values()]
        detected_pks = get_motherduck_primary_keys(
            lambda: closing_connection(config.motherduck_token, database), locations
        )

        schemas: list[SourceSchema] = []
        for display_name, entry in discovered.items():
            columns: list[tuple[str, str, bool]] = entry["columns"]
            incremental_field_tuples = filter_motherduck_incremental_fields(columns)
            incremental_fields: list[IncrementalField] = [
                {
                    "label": field_name,
                    "type": field_type,
                    "field": field_name,
                    "field_type": field_type,
                }
                for field_name, field_type in incremental_field_tuples
            ]
            location = (entry["database"], entry["schema"], entry["table"])
            schemas.append(
                SourceSchema(
                    name=display_name,
                    supports_incremental=len(incremental_fields) > 0,
                    supports_append=len(incremental_fields) > 0,
                    incremental_fields=incremental_fields,
                    row_count=entry.get("row_count"),
                    columns=columns,
                    source_catalog=entry["database"],
                    source_schema=entry["schema"],
                    source_table_name=entry["table"],
                    detected_primary_keys=detected_pks.get(location),
                )
            )
        return schemas

    def validate_credentials(
        self,
        config: MotherduckSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if not (config.motherduck_token or "").strip():
            return False, "A MotherDuck access token is required."
        try:
            self.get_schemas(config, team_id, names=[schema_name] if schema_name else None, api_version=api_version)
        except MotherDuckConnectionError as e:
            return False, str(e) or GENERIC_CONNECTION_ERROR
        except duckdb.Error as e:
            return False, translate_motherduck_error(e)
        except Exception as e:
            capture_exception(e)
            return False, GENERIC_CONNECTION_ERROR
        return True, None

    def get_connection_metadata(self, config: MotherduckSourceConfig, team_id: int) -> dict[str, object]:
        return get_motherduck_connection_metadata(config.motherduck_token, self.normalized_database(config))

    def source_for_pipeline(self, config: MotherduckSourceConfig, inputs: SourceInputs) -> SourceResponse:
        from products.warehouse_sources.backend.models.external_data_schema import ExternalDataSchema

        schema_model = ExternalDataSchema.objects.select_related("source").get(id=inputs.schema_id)
        database = self.normalized_database(config)

        # Resolve the table's physical location from persisted schema metadata; fall back to
        # parsing the display name for rows created before metadata was stored.
        schema_metadata = (schema_model.sync_type_config or {}).get("schema_metadata") or {}
        source_catalog = schema_metadata.get("source_catalog")
        source_schema = schema_metadata.get("source_schema")
        source_table_name = schema_metadata.get("source_table_name")
        if not (isinstance(source_schema, str) and isinstance(source_table_name, str)):
            parts = inputs.schema_name.split(".")
            if len(parts) == 3:
                source_catalog, source_schema, source_table_name = parts
            elif len(parts) == 2:
                source_catalog = database
                source_schema, source_table_name = parts
            else:
                source_catalog, source_schema, source_table_name = database, "main", inputs.schema_name
        if not isinstance(source_catalog, str) or not source_catalog:
            if database is None:
                raise MotherDuckConnectionError(
                    f"Could not resolve the MotherDuck database for table '{inputs.schema_name}'."
                )
            source_catalog = database

        primary_keys: list[str] | None = None
        primary_key_columns = (schema_model.sync_type_config or {}).get("primary_key_columns")
        if isinstance(primary_key_columns, list) and primary_key_columns:
            primary_keys = [str(column) for column in primary_key_columns]

        return motherduck_source(
            token=config.motherduck_token,
            database=database,
            display_name=inputs.schema_name,
            location=(source_catalog, source_schema, source_table_name),
            primary_keys=primary_keys,
            should_use_incremental_field=inputs.should_use_incremental_field,
            incremental_field=inputs.incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
        )

    def reconcile_schema_metadata(
        self,
        source: "ExternalDataSource",
        source_schemas: list[SourceSchema],
        team_id: int,
    ) -> list[str]:
        """Persist per-schema column metadata so the column picker populates. MotherDuck isn't a
        `SQLSource`, but the reconcile step is driver-agnostic, so we reuse the shared helper."""
        return reconcile_source_schema_metadata(source, source_schemas, team_id)
