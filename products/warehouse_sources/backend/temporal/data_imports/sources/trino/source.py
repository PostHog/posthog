from __future__ import annotations

from typing import Optional, cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigConverter,
    SourceFieldSelectConfigOption,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import ValidateDatabaseHostMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql import (
    build_incremental_fields,
    resolve_detected_primary_keys,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.sql.base import SQLSource
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.trino import TrinoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.trino.trino import (
    TRINO_COLUMN_NOT_FOUND_ERROR,
    TRINO_KNOWN_ERROR_MESSAGES,
    TRINO_SCHEMA_NOT_FOUND_ERROR,
    TRINO_TABLE_NOT_FOUND_ERROR,
    TrinoImplementation,
    TrinoSchemaDiscoveryError,
    connect_trino,
    discover_trino_schemas,
    trino_error_to_message,
    trino_failures_as_discovery_error,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

_TRINO_IMPLEMENTATION = TrinoImplementation()


@SourceRegistry.register
class TrinoSource(SQLSource[TrinoSourceConfig], ValidateDatabaseHostMixin):
    api_docs_url = "https://trino.io/docs/current/client/python.html"

    @property
    def get_implementation(self) -> TrinoImplementation:
        return _TRINO_IMPLEMENTATION

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TRINO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.TRINO,
            category=DataWarehouseSourceCategory.DATABASES,
            keywords=["sql", "presto", "starburst"],
            label="Trino",
            caption="Connect to Trino to run read-only SQL against the catalogs available to this user.",
            iconPath="/static/services/trino.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/trino",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="host",
                        label="Host",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="trino.example.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="port",
                        label="Port",
                        type=SourceFieldInputConfigType.NUMBER,
                        required=True,
                        placeholder="443",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="catalog",
                        label="Catalog",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="hive",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="schema",
                        label="Schema (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="Leave blank to include all schemas",
                        secret=False,
                    ),
                    SourceFieldSelectConfig(
                        name="auth_type",
                        label="Authentication type",
                        required=True,
                        defaultValue="password",
                        options=[
                            SourceFieldSelectConfigOption(
                                label="Password",
                                value="password",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="user",
                                            label="Username",
                                            type=SourceFieldInputConfigType.TEXT,
                                            required=True,
                                            placeholder="posthog",
                                            secret=False,
                                        ),
                                        SourceFieldInputConfig(
                                            name="password",
                                            label="Password",
                                            type=SourceFieldInputConfigType.PASSWORD,
                                            required=False,
                                            placeholder="",
                                            secret=True,
                                        ),
                                    ],
                                ),
                            ),
                            SourceFieldSelectConfigOption(
                                label="JWT token",
                                value="jwt",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="user",
                                            label="Username",
                                            type=SourceFieldInputConfigType.TEXT,
                                            required=True,
                                            placeholder="posthog",
                                            secret=False,
                                        ),
                                        SourceFieldInputConfig(
                                            name="token",
                                            label="Token",
                                            type=SourceFieldInputConfigType.PASSWORD,
                                            required=False,
                                            placeholder="",
                                            secret=True,
                                        ),
                                    ],
                                ),
                            ),
                            SourceFieldSelectConfigOption(
                                label="No authentication",
                                value="none",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="user",
                                            label="Username",
                                            type=SourceFieldInputConfigType.TEXT,
                                            required=True,
                                            placeholder="posthog",
                                            secret=False,
                                        ),
                                    ],
                                ),
                            ),
                        ],
                    ),
                    SourceFieldSelectConfig(
                        name="use_ssl",
                        label="Use HTTPS?",
                        required=True,
                        defaultValue="true",
                        converter=SourceFieldSelectConfigConverter.STR_TO_BOOL,
                        options=[
                            SourceFieldSelectConfigOption(label="Yes", value="true"),
                            SourceFieldSelectConfigOption(label="No", value="false"),
                        ],
                    ),
                    SourceFieldSelectConfig(
                        name="verify_ssl",
                        label="Verify TLS certificate?",
                        required=True,
                        defaultValue="true",
                        converter=SourceFieldSelectConfigConverter.STR_TO_BOOL,
                        options=[
                            SourceFieldSelectConfigOption(label="Yes", value="true"),
                            SourceFieldSelectConfigOption(label="No", value="false"),
                        ],
                    ),
                ],
            ),
        )

    def validate_credentials(
        self, config: TrinoSourceConfig, team_id: int, schema_name: Optional[str] = None, api_version: str | None = None
    ) -> tuple[bool, str | None]:
        is_valid, error = self.is_database_host_valid(config.host, team_id)
        if not is_valid:
            return False, error
        try:
            with connect_trino(config) as connection:
                cursor = connection.cursor()
                cursor.execute("SELECT 1")
                cursor.fetchone()
        except Exception as exc:
            return False, trino_error_to_message(exc)
        return True, None

    def get_schemas(
        self,
        config: TrinoSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        is_valid, error = self.is_database_host_valid(config.host, team_id)
        if not is_valid:
            raise ValueError(error or "Invalid Trino host.")
        with trino_failures_as_discovery_error(), connect_trino(config) as connection:
            discovered = discover_trino_schemas(connection.cursor(), config, names)

        # Built from the discovered tables rather than through `SQLSource.get_schemas`, because a
        # schema name can contain a dot (nested Iceberg namespaces), so the display name alone
        # cannot be split back into its schema and table.
        incremental_filter = self.get_implementation.get_incremental_filter()
        schemas: list[SourceSchema] = []
        for table in discovered:
            columns = [(column.name, column.data_type, column.nullable) for column in table.columns]
            incremental_fields = incremental_filter(columns)
            schemas.append(
                SourceSchema(
                    name=table.name if config.schema else f"{table.schema}.{table.name}",
                    supports_incremental=bool(incremental_fields),
                    supports_append=bool(incremental_fields),
                    incremental_fields=build_incremental_fields(incremental_fields),
                    columns=columns,
                    source_catalog=table.catalog,
                    source_schema=table.schema,
                    source_table_name=table.name,
                    detected_primary_keys=resolve_detected_primary_keys(None, columns),
                )
            )
        return schemas

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # Schema discovery hands back Trino's own verdict, so the API must show it. The message keys
        # match in every consumer, because `str(TrinoSchemaDiscoveryError(...))` is the message. The
        # last key stops PostHog filing an unrecognized Trino-side failure, which is the remote
        # server's fault.
        #
        # NOTE: that last key only takes effect in the refresh-schemas classifier, which compares
        # against `f"{type(error).__name__}: {message}"`. A message-only consumer such as
        # `incremental_fields` compares against `str(e)`, so an unrecognized failure there is still
        # filed. Closing that gap needs a shared classifier across the schema-discovery views, not a
        # per-source key. Mirrors the note on the Stripe source.
        return {
            **self.default_non_retryable_errors(),
            **{message: message for message in TRINO_KNOWN_ERROR_MESSAGES},
            TRINO_TABLE_NOT_FOUND_ERROR: TRINO_TABLE_NOT_FOUND_ERROR,
            # A query failure names its Trino error code in the text, for example
            # `TrinoUserError(type=USER_ERROR, name=TABLE_NOT_FOUND, ...)`.
            "name=TABLE_NOT_FOUND": TRINO_TABLE_NOT_FOUND_ERROR,
            "name=SCHEMA_NOT_FOUND": TRINO_SCHEMA_NOT_FOUND_ERROR,
            "name=COLUMN_NOT_FOUND": TRINO_COLUMN_NOT_FOUND_ERROR,
            TrinoSchemaDiscoveryError.__name__: None,
        }
