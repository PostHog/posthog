from __future__ import annotations

from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigConverter,
    SourceFieldSelectConfigOption,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import ValidateDatabaseHostMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.trino import TrinoSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.trino.trino import (
    connect_trino,
    discover_trino_schemas,
    trino_error_to_message,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TrinoSource(SimpleSource[TrinoSourceConfig], ValidateDatabaseHostMixin):
    supports_column_selection = True
    supports_scheduled_sync = False
    api_docs_url = "https://trino.io/docs/current/client/python.html"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TRINO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TRINO,
            category=DataWarehouseSourceCategory.DATABASES,
            keywords=["sql", "presto", "starburst"],
            label="Trino",
            caption="Connect to Trino to run read-only SQL against the catalogs available to this user.",
            iconPath="/static/services/trino.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/trino",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
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
        with connect_trino(config) as connection:
            discovered = discover_trino_schemas(connection.cursor(), config, names)
        return [
            SourceSchema(
                name=table.name if config.schema else f"{table.schema}.{table.name}",
                supports_incremental=False,
                supports_append=False,
                columns=[(column.name, column.data_type, column.nullable) for column in table.columns],
                source_catalog=table.catalog,
                source_schema=table.schema,
                source_table_name=table.name,
            )
            for table in discovered
        ]
