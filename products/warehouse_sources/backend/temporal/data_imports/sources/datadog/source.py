from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.datadog.datadog import (
    DatadogResumeConfig,
    datadog_source,
    validate_credentials as validate_datadog_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.datadog.settings import (
    DATADOG_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    LIMITED_RETENTION_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import DatadogSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class DatadogSource(ResumableSource[DatadogSourceConfig, DatadogResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DATADOG

    @property
    def connection_host_fields(self) -> list[str]:
        # The API/application keys are sent to the host derived from `site`, so changing the site
        # must re-require the secrets rather than reusing them against a different host.
        return ["site"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.DATADOG,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Datadog",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Connect your Datadog account to sync logs, events, monitors, dashboards, and more into the PostHog Data warehouse.

Create an API key and an application key in your [Datadog organization settings](https://app.datadoghq.com/organization-settings/api-keys). The application key should be granted read scopes for the data you want to sync, for example:
- `dashboards_read`
- `monitors_read`
- `incident_read`
- `slos_read`
- `synthetics_read`
- `user_access_read`

Logs, audit logs, and events read access is governed by your Datadog account's data retention.""",
            iconPath="/static/services/datadog.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/datadog",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="site",
                        label="Datadog site",
                        required=True,
                        defaultValue="datadoghq.com",
                        options=[
                            SourceFieldSelectConfigOption(label="US1 (datadoghq.com)", value="datadoghq.com"),
                            SourceFieldSelectConfigOption(label="US3 (us3.datadoghq.com)", value="us3.datadoghq.com"),
                            SourceFieldSelectConfigOption(label="US5 (us5.datadoghq.com)", value="us5.datadoghq.com"),
                            SourceFieldSelectConfigOption(label="EU1 (datadoghq.eu)", value="datadoghq.eu"),
                            SourceFieldSelectConfigOption(label="AP1 (ap1.datadoghq.com)", value="ap1.datadoghq.com"),
                            SourceFieldSelectConfigOption(label="US1-FED (ddog-gov.com)", value="ddog-gov.com"),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Datadog API key",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="application_key",
                        label="Application key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Datadog application key",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid Datadog API key. Generate a valid key and reconnect.",
            "403 Client Error": "Your Datadog application key is missing the required read scopes for this data. Grant the scopes and reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.datadog.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: DatadogSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=DATADOG_ENDPOINTS[endpoint].supports_incremental,
                supports_append=DATADOG_ENDPOINTS[endpoint].supports_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                description=(
                    "Limited to your Datadog account's retention window on initial sync"
                    if endpoint in LIMITED_RETENTION_ENDPOINTS
                    else None
                ),
            )
            for endpoint in list(ENDPOINTS)
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: DatadogSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_datadog_credentials(config.site, config.api_key, config.application_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[DatadogResumeConfig]:
        return ResumableSourceManager[DatadogResumeConfig](inputs, DatadogResumeConfig)

    def source_for_pipeline(
        self,
        config: DatadogSourceConfig,
        resumable_source_manager: ResumableSourceManager[DatadogResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return datadog_source(
            site=config.site,
            api_key=config.api_key,
            app_key=config.application_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
