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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import UptimerobotSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.uptimerobot.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    RESPONSE_TIMES_INITIAL_LOOKBACK_DAYS,
    UPTIMEROBOT_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.uptimerobot.uptimerobot import (
    AUTH_ERROR_PREFIX,
    UptimeRobotResumeConfig,
    uptimerobot_source,
    validate_credentials as validate_uptimerobot_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class UptimerobotSource(ResumableSource[UptimerobotSourceConfig, UptimeRobotResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.UPTIMEROBOT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.UPTIMEROBOT,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="UptimeRobot",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your UptimeRobot API key to pull your uptime monitoring data into the PostHog Data warehouse.

Use your account's **read-only API key**, created under [Integrations & API](https://dashboard.uptimerobot.com/integrations) in your UptimeRobot dashboard. Monitor-specific API keys only grant access to a single monitor, so the alert contacts, maintenance windows, and status pages tables won't sync with one.""",
            iconPath="/static/services/uptimerobot.png",
            docsUrl="https://posthog.com/docs/cdp/sources/uptimerobot",
            keywords=["uptime", "monitoring"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="ur1234567-...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.uptimerobot.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # UptimeRobot returns HTTP 200 with an in-body error for bad credentials; the transport
            # raises with this stable prefix when the API rejects the key. Retrying can never fix a
            # credential problem, so stop the sync.
            AUTH_ERROR_PREFIX: "Your UptimeRobot API key is invalid or has been revoked. Create a new read-only API key under Integrations & API in your UptimeRobot dashboard, then reconnect.",
        }

    def get_schemas(
        self,
        config: UptimerobotSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        def _description(endpoint: str) -> str | None:
            if endpoint == "monitor_logs":
                return "Up/down/pause event history per monitor. Incremental syncs only fetch logs newer than the last synced event"
            if endpoint == "response_times":
                return (
                    f"Response-time samples per monitor, fetched in 7-day windows. "
                    f"Only syncs the last {RESPONSE_TIMES_INITIAL_LOOKBACK_DAYS} days on initial sync"
                )
            return None

        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = UPTIMEROBOT_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                supports_incremental=endpoint_config.supports_incremental,
                supports_append=endpoint_config.supports_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                description=_description(endpoint),
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: UptimerobotSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_uptimerobot_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[UptimeRobotResumeConfig]:
        return ResumableSourceManager[UptimeRobotResumeConfig](inputs, UptimeRobotResumeConfig)

    def source_for_pipeline(
        self,
        config: UptimerobotSourceConfig,
        resumable_source_manager: ResumableSourceManager[UptimeRobotResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return uptimerobot_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
