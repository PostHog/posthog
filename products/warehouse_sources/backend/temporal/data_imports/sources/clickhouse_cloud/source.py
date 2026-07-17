from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clickhouse_cloud.clickhouse_cloud import (
    ClickhouseCloudResumeConfig,
    clickhouse_cloud_source,
    validate_credentials as validate_clickhouse_cloud_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clickhouse_cloud.settings import (
    CLICKHOUSE_CLOUD_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    ClickhouseCloudSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ClickhouseCloudSource(ResumableSource[ClickhouseCloudSourceConfig, ClickhouseCloudResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CLICKHOUSECLOUD

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CLICKHOUSE_CLOUD,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="ClickHouse Cloud (ClickHouse, Inc.)",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your ClickHouse Cloud API key to pull your organization's usage costs, service inventory, and audit log into the PostHog Data warehouse.

Generate an API key from your [ClickHouse Cloud console](https://console.clickhouse.cloud/) under your organization's **API keys** settings. Keys with the **Admin** role can read every table; a **Developer**-scoped key may not have access to the usage cost and audit log tables.""",
            iconPath="/static/services/clickhouse_cloud.png",
            docsUrl="https://posthog.com/docs/cdp/sources/clickhouse-cloud",
            keywords=["clickhouse", "cloud costs", "finops", "billing"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="key_id",
                        label="API key ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="key_secret",
                        label="API key secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.clickhouse_cloud.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.clickhouse.cloud": "Your ClickHouse Cloud API key is invalid or has been revoked. Generate a new API key in the ClickHouse Cloud console, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.clickhouse.cloud": "Your ClickHouse Cloud API key does not have permission to read this data. Use a key with the Admin role, then reconnect.",
        }

    def get_schemas(
        self,
        config: ClickhouseCloudSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = CLICKHOUSE_CLOUD_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                supports_incremental=endpoint_config.supports_incremental,
                supports_append=endpoint_config.supports_append,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
                default_incremental_lookback_seconds=endpoint_config.default_incremental_lookback_seconds,
                description=endpoint_config.description,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: ClickhouseCloudSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_clickhouse_cloud_credentials(config.key_id, config.key_secret):
            return True, None

        return False, "Invalid ClickHouse Cloud API key ID or secret"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ClickhouseCloudResumeConfig]:
        return ResumableSourceManager[ClickhouseCloudResumeConfig](inputs, ClickhouseCloudResumeConfig)

    def source_for_pipeline(
        self,
        config: ClickhouseCloudSourceConfig,
        resumable_source_manager: ResumableSourceManager[ClickhouseCloudResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return clickhouse_cloud_source(
            key_id=config.key_id,
            key_secret=config.key_secret,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
