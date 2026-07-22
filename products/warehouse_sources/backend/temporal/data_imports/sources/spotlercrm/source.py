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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.spotlercrm import (
    SpotlerCRMSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.spotlercrm.settings import (
    ENDPOINT_DESCRIPTIONS,
    ENDPOINT_SHOULD_SYNC_DEFAULT,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.spotlercrm.spotlercrm import (
    SpotlerCRMResumeConfig,
    get_endpoint_permissions as get_spotlercrm_endpoint_permissions,
    spotlercrm_source,
    validate_credentials as validate_spotlercrm_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SpotlerCRMSource(ResumableSource[SpotlerCRMSourceConfig, SpotlerCRMResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v4",)
    default_version = "v4"
    api_docs_url = "https://support.reallysimplesystems.com/api-v4/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SPOTLERCRM

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "403 Client Error": "Your Spotler CRM access token is invalid or expired, or your plan doesn't include this record type. Generate a new token under Settings / Integrations / API V4 and reconnect.",
            "402 Client Error": "Your Spotler CRM access token was rejected. Generate a new token under Settings / Integrations / API V4 and reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.spotlercrm.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: SpotlerCRMSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            descriptions=ENDPOINT_DESCRIPTIONS,
            should_sync_default=ENDPOINT_SHOULD_SYNC_DEFAULT,
        )

    def validate_credentials(
        self,
        config: SpotlerCRMSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_spotlercrm_credentials(config.access_token)

    def get_endpoint_permissions(
        self, config: SpotlerCRMSourceConfig, team_id: int, endpoints: list[str], api_version: str | None = None
    ) -> dict[str, str | None]:
        return get_spotlercrm_endpoint_permissions(config.access_token, endpoints)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SpotlerCRMResumeConfig]:
        return ResumableSourceManager[SpotlerCRMResumeConfig](inputs, SpotlerCRMResumeConfig)

    def source_for_pipeline(
        self,
        config: SpotlerCRMSourceConfig,
        resumable_source_manager: ResumableSourceManager[SpotlerCRMResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return spotlercrm_source(
            access_token=config.access_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SPOTLER_CRM,
            category=DataWarehouseSourceCategory.CRM,
            label="Spotler CRM",
            caption="""Enter your Spotler CRM API access token to pull your CRM data into the PostHog Data warehouse.

Generate a token in Spotler CRM under **Settings / Integrations / API V4** — it's shown only once, so copy it when you create it.

Some record types need paid add-ons: Campaigns requires the Marketing tool, and Cases requires the Service & Support tool.""",
            docsUrl="https://posthog.com/docs/cdp/sources/spotlercrm",
            iconPath="/static/services/spotlercrm.png",
            keywords=["really simple systems", "spotler", "rss crm"],
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="access_token",
                        label="API access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Enter your Spotler CRM access token",
                        secret=True,
                    ),
                ],
            ),
        )
