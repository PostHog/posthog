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
from products.warehouse_sources.backend.temporal.data_imports.sources.customerly.customerly import (
    CustomerlyResumeConfig,
    customerly_source,
    validate_credentials as validate_customerly_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.customerly.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CustomerlySourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CustomerlySource(ResumableSource[CustomerlySourceConfig, CustomerlyResumeConfig]):
    api_docs_url = "https://docs.customerly.io/en/collections/5530-api"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CUSTOMERLY

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "Customerly authentication failed": "Your Customerly access token is invalid or expired. Please generate a new token in Project Settings > Installation > Public API and reconnect.",
            "401 Client Error: Unauthorized for url: https://api.customerly.io": "Your Customerly access token is invalid or expired. Please generate a new token in Project Settings > Installation > Public API and reconnect.",
            "403 Client Error: Forbidden for url: https://api.customerly.io": "Your Customerly access token does not have the required permissions. Please check the token and try again.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CUSTOMERLY,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="Customerly",
            caption="""Enter your Customerly access token to pull your Customerly data into the PostHog Data warehouse.

You can find your access token in your Customerly project under **Project Settings** > **Installation** > **Public API** — see the [Customerly guide](https://docs.customerly.io/en/api/how-to-obtain-your-api-access-token-in-customerly).""",
            iconPath="/static/services/customerly.png",
            docsUrl="https://posthog.com/docs/cdp/sources/customerly",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.customerly.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: CustomerlySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self, config: CustomerlySourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_customerly_credentials(config.access_token):
            return True, None

        return False, "Invalid Customerly access token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CustomerlyResumeConfig]:
        return ResumableSourceManager[CustomerlyResumeConfig](inputs, CustomerlyResumeConfig)

    def source_for_pipeline(
        self,
        config: CustomerlySourceConfig,
        resumable_source_manager: ResumableSourceManager[CustomerlyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return customerly_source(
            access_token=config.access_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
