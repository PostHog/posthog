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

from products.warehouse_sources.backend.temporal.data_imports.sources.cloudability.cloudability import (
    CloudabilityResumeConfig,
    cloudability_source,
    validate_credentials as validate_cloudability_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudability.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cloudability import (
    CloudabilitySourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CloudabilitySource(ResumableSource[CloudabilitySourceConfig, CloudabilityResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v3",)
    default_version = "v3"
    api_docs_url = "https://www.ibm.com/docs/en/cloudability-commercial/cloudability-premium/saas?topic=api-getting-started-cloudability-v3"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CLOUDABILITY

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Cloudability authentication failed. Please check your API key and region.",
            "Unauthorized for url": "Cloudability authentication failed. Please check your API key and region.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.cloudability.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: CloudabilitySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: CloudabilitySourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_cloudability_credentials(config.api_key, config.region):
            return True, None

        return False, "Invalid credentials. Check your API key and region."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CloudabilityResumeConfig]:
        return ResumableSourceManager[CloudabilityResumeConfig](inputs, CloudabilityResumeConfig)

    def source_for_pipeline(
        self,
        config: CloudabilitySourceConfig,
        resumable_source_manager: ResumableSourceManager[CloudabilityResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return cloudability_source(
            api_key=config.api_key,
            region=config.region,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            view_id=config.view_id or None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CLOUDABILITY,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Apptio Cloudability (IBM)",
            keywords=["cloudability", "finops", "cloud cost", "apptio"],
            docsUrl="https://posthog.com/docs/cdp/sources/cloudability",
            iconPath="/static/services/cloudability.png",
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
                        caption="Generate this in Cloudability under the gear icon > Preferences > Enable Access.",
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="us",
                        options=[
                            SourceFieldSelectConfigOption(label="US (api.cloudability.com)", value="us"),
                            SourceFieldSelectConfigOption(label="EU (api-eu.cloudability.com)", value="eu"),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="view_id",
                        label="Default view ID (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="",
                        secret=False,
                        caption="Scopes the Anomalies table to one Cloudability view. Leave blank to use your organization's default view.",
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )
