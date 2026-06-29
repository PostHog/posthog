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
from products.warehouse_sources.backend.temporal.data_imports.sources.active_campaign.active_campaign import (
    ActiveCampaignResumeConfig,
    active_campaign_source,
    validate_credentials as validate_active_campaign_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.active_campaign.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    ActiveCampaignSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ActiveCampaignSource(ResumableSource[ActiveCampaignSourceConfig, ActiveCampaignResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ACTIVECAMPAIGN

    @property
    def connection_host_fields(self) -> list[str]:
        # `api_url` is where the stored API key is sent; retargeting it must re-require the key.
        return ["api_url"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ACTIVE_CAMPAIGN,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="ActiveCampaign",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your ActiveCampaign API URL and key to sync your CRM and marketing data into the PostHog Data warehouse.

You can find both in your ActiveCampaign account under **Settings > Developer**. The API key is account-wide and grants read access to every endpoint listed below.""",
            iconPath="/static/services/activecampaign.png",
            docsUrl="https://posthog.com/docs/cdp/sources/active-campaign",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_url",
                        label="API URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://youraccount.api-us1.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid ActiveCampaign credentials. Please check your API URL and key and reconnect.",
            "403 Client Error": "Access forbidden. Please check that your ActiveCampaign API key is valid and reconnect.",
            "Unauthorized for url": "Invalid ActiveCampaign credentials. Please check your API URL and key and reconnect.",
        }

    def get_schemas(
        self,
        config: ActiveCampaignSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=(fields := INCREMENTAL_FIELDS.get(endpoint)) is not None,
                supports_append=fields is not None,
                incremental_fields=fields or [],
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: ActiveCampaignSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_active_campaign_credentials(config.api_url, config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ActiveCampaignResumeConfig]:
        return ResumableSourceManager[ActiveCampaignResumeConfig](inputs, ActiveCampaignResumeConfig)

    def source_for_pipeline(
        self,
        config: ActiveCampaignSourceConfig,
        resumable_source_manager: ResumableSourceManager[ActiveCampaignResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return active_campaign_source(
            api_url=config.api_url,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )
