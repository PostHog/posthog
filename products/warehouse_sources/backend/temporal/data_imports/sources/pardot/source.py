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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pardot import PardotSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.pardot.pardot import (
    PardotResumeConfig,
    pardot_source,
    validate_credentials as validate_pardot_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pardot.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PardotSource(ResumableSource[PardotSourceConfig, PardotResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v5",)
    default_version = "v5"
    api_docs_url = "https://developer.salesforce.com/docs/marketing/pardot/guide/version5overview.html"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PARDOT

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.pardot.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "400 Client Error: Bad Request for url: https://login.salesforce.com/services/oauth2/token": "Salesforce rejected your refresh token. Reauthorize the connected app and paste in the new refresh token.",
            "400 Client Error: Bad Request for url: https://test.salesforce.com/services/oauth2/token": "Salesforce rejected your refresh token. Reauthorize the connected app and paste in the new refresh token.",
            "401 Client Error: Unauthorized for url": "Account Engagement rejected the access token. Check your connected app credentials and reconnect.",
            "403 Client Error: Forbidden for url": "Account Engagement denied access. Check that the user has API access and that the business unit ID is correct.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PARDOT,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            keywords=["salesforce pardot", "marketing cloud account engagement"],
            label="Pardot",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Connect Salesforce Marketing Cloud Account Engagement (formerly Pardot) to pull your marketing data into the PostHog Data warehouse.

Create a Salesforce connected app with the `pardot_api` and `refresh_token` scopes, authorize it, and keep the refresh token it returns. Your business unit ID is the 18-character ID starting with `0Uv`, in Salesforce Setup under **Account Engagement → Business Unit Setup**.""",
            iconPath="/static/services/pardot.png",
            docsUrl="https://posthog.com/docs/cdp/sources/pardot",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="environment",
                        label="Environment",
                        required=True,
                        defaultValue="production",
                        options=[
                            SourceFieldSelectConfigOption(label="Production", value="production"),
                            SourceFieldSelectConfigOption(label="Sandbox", value="sandbox"),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="business_unit_id",
                        label="Business unit ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="0Uv...",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="client_id",
                        label="Consumer key",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="3MVG9...",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="client_secret",
                        label="Consumer secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="refresh_token",
                        label="Refresh token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_schemas(
        self,
        config: PardotSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: PardotSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_pardot_credentials(
            environment=config.environment,
            business_unit_id=config.business_unit_id,
            client_id=config.client_id,
            client_secret=config.client_secret,
            refresh_token=config.refresh_token,
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PardotResumeConfig]:
        # Each endpoint pages with its own opaque token, so isolate resume state per schema —
        # a retry that switches endpoints must not replay another endpoint's token.
        return ResumableSourceManager[PardotResumeConfig](inputs, PardotResumeConfig).with_namespace(inputs.schema_name)

    def source_for_pipeline(
        self,
        config: PardotSourceConfig,
        resumable_source_manager: ResumableSourceManager[PardotResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return pardot_source(
            environment=config.environment,
            business_unit_id=config.business_unit_id,
            client_id=config.client_id,
            client_secret=config.client_secret,
            refresh_token=config.refresh_token,
            endpoint=inputs.schema_name,
            api_version=self.resolve_api_version(inputs.api_version),
            resumable_source_manager=resumable_source_manager,
            logger=inputs.logger,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
