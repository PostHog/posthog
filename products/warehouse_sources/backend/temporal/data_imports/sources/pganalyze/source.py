from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PgAnalyzeSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.pganalyze.pganalyze import (
    pganalyze_source,
    validate_credentials as validate_pganalyze_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pganalyze.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PgAnalyzeSource(SimpleSource[PgAnalyzeSourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PGANALYZE

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "pganalyze authentication failed. Please check your API token.",
            "403 Client Error": "pganalyze authentication failed. Please check your API token.",
            "Invalid pganalyze API token": "pganalyze authentication failed. Please check your API token and organization slug.",
        }

    def get_schemas(
        self,
        config: PgAnalyzeSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=bool(INCREMENTAL_FIELDS.get(endpoint)),
                supports_append=bool(INCREMENTAL_FIELDS.get(endpoint)),
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in list(ENDPOINTS)
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: PgAnalyzeSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_pganalyze_credentials(
            api_key=config.api_key,
            organization_slug=config.organization_slug,
            api_url=config.api_url,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PG_ANALYZE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="pganalyze",
            caption="Connect pganalyze to sync Postgres performance issues, query stats, and server metadata into the PostHog Data warehouse.",
            iconPath="/static/services/pganalyze.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/pganalyze",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Read-only pganalyze API key",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="organization_slug",
                        label="Organization slug",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="your-organization-slug",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_url",
                        label="API URL (optional, for self-hosted Enterprise Server)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="https://app.pganalyze.com/graphql",
                        secret=False,
                    ),
                ],
            ),
        )

    def source_for_pipeline(self, config: PgAnalyzeSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return pganalyze_source(
            api_key=config.api_key,
            api_url=config.api_url,
            organization_slug=config.organization_slug,
            endpoint_name=inputs.schema_name,
            logger=inputs.logger,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
