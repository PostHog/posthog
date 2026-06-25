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
from products.warehouse_sources.backend.temporal.data_imports.sources.campaign_monitor.campaign_monitor import (
    CampaignMonitorResumeConfig,
    campaign_monitor_source,
    validate_credentials as validate_campaign_monitor_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.campaign_monitor.settings import (
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
    CampaignMonitorSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CampaignMonitorSource(ResumableSource[CampaignMonitorSourceConfig, CampaignMonitorResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CAMPAIGNMONITOR

    @property
    def connection_host_fields(self) -> list[str]:
        # `client_id` selects which Campaign Monitor client the stored API key is used against.
        # Editing it on an existing source must force the API key to be re-entered — otherwise an
        # editor could retarget the preserved key at another client it can access.
        return ["client_id"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Your Campaign Monitor API key is invalid or expired. Please generate a new key and reconnect.",
            "403 Client Error: Forbidden for url": "Your Campaign Monitor API key does not have access to this client or resource. Please check the key's permissions and try again.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.campaign_monitor.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: CampaignMonitorSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                # Every endpoint ships full refresh until the server-side `date` filter is verified
                # against a live account (see settings.py for the incremental migration path), so
                # INCREMENTAL_FIELDS is empty for all endpoints today.
                supports_incremental=bool(INCREMENTAL_FIELDS[endpoint]),
                supports_append=bool(INCREMENTAL_FIELDS[endpoint]),
                incremental_fields=INCREMENTAL_FIELDS[endpoint],
            )
            for endpoint in list(ENDPOINTS)
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: CampaignMonitorSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_campaign_monitor_credentials(config.api_key):
            return True, None

        return False, "Invalid Campaign Monitor API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CampaignMonitorResumeConfig]:
        return ResumableSourceManager[CampaignMonitorResumeConfig](inputs, CampaignMonitorResumeConfig)

    def source_for_pipeline(
        self,
        config: CampaignMonitorSourceConfig,
        resumable_source_manager: ResumableSourceManager[CampaignMonitorResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return campaign_monitor_source(
            api_key=config.api_key,
            client_id=config.client_id,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CAMPAIGN_MONITOR,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Campaign Monitor",
            caption="""Enter your Campaign Monitor (CreateSend) API key and Client ID to pull your email marketing data into the PostHog Data warehouse.

Create an API key in your [Campaign Monitor account settings](https://www.campaignmonitor.com/api/) under **Account settings → API keys**.

Your **Client ID** identifies the client whose data you want to sync. You can find it in the client's **Settings** page, or by calling the `clients.json` API endpoint.""",
            iconPath="/static/services/campaign_monitor.png",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="client_id",
                        label="Client ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                ],
            ),
        )
