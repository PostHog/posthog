from typing import Optional, cast

from products.warehouse_sources.backend.facade.codebase_detection import NOT_DETECTABLE
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.unityads import (
    UnityAdsSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.unity_ads.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    LOOKBACK,
    MERGE_ONLY,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.unity_ads.unity_ads import (
    INVALID_ORGANIZATION_ID,
    UnityAdsResumeConfig,
    unity_ads_source,
    validate_credentials as validate_unity_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class UnityAdsSource(ResumableSource[UnityAdsSourceConfig, UnityAdsResumeConfig]):
    codebase_detection = NOT_DETECTABLE

    lists_tables_without_credentials = True
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://docs.unity.com/en-us/oas-statistics/2.0.0"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.UNITYADS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://services.api.unity.com": (
                "Unity rejected the service account key. Create a new key and update the source."
            ),
            "403 Client Error: Forbidden for url: https://services.api.unity.com": (
                "The service account cannot read statistics. Give it the Advertise Stats API Viewer role in Unity."
            ),
            "404 Client Error: Not Found for url: https://services.api.unity.com": (
                "Unity found no organization with that ID. Use the Organization core ID from Settings in Unity Ads."
            ),
            INVALID_ORGANIZATION_ID: None,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.unity_ads.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: UnityAdsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(
            ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only=MERGE_ONLY, default_incremental_lookback_seconds=LOOKBACK
        )

    def validate_credentials(
        self,
        config: UnityAdsSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_unity_credentials(config.organization_id, config.key_id, config.secret_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[UnityAdsResumeConfig]:
        return ResumableSourceManager[UnityAdsResumeConfig](inputs, UnityAdsResumeConfig)

    def source_for_pipeline(
        self,
        config: UnityAdsSourceConfig,
        resumable_source_manager: ResumableSourceManager[UnityAdsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return unity_ads_source(
            organization_id=config.organization_id,
            key_id=config.key_id,
            secret_key=config.secret_key,
            endpoint=inputs.schema_name,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.UNITYADS,
            category=DataWarehouseSourceCategory.ADVERTISING,
            keywords=["unity", "user acquisition"],
            label="Unity Ads",
            caption="Sync daily user acquisition statistics for your Unity Ads campaigns, by campaign and by country.",
            docsUrl="https://posthog.com/docs/cdp/sources/unity-ads",
            iconPath="/static/services/unity_ads.png",
            releaseStatus=ReleaseStatus.BETA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="organization_id",
                        label="Organization core ID",
                        caption="Shown under Settings in the Unity Ads user acquisition dashboard.",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="5772916123937",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="key_id",
                        label="Key ID",
                        caption="Create a service account key with the Advertise Stats API Viewer role.",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="secret_key",
                        label="Secret key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )
