from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.reverb import ReverbSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.reverb.reverb import (
    ReverbResumeConfig,
    reverb_source,
    validate_credentials as validate_reverb_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.reverb.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ReverbSource(ResumableSource[ReverbSourceConfig, ReverbResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    # Reverb requires the `Accept-Version` header on every request. "3.0" is the vendor's
    # current recommended version (the undocumented default is the legacy "1.0").
    supported_versions = ("3.0",)
    default_version = "3.0"
    api_docs_url = "https://www.reverb-api.com/docs/http-headers"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.REVERB

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.REVERB,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Reverb",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Reverb personal access token to pull your shop's orders, listings, and payouts into the PostHog Data warehouse.

Create a token from **My Profile → API & Integrations** in your Reverb account, with the `read_listings`, `read_orders`, and `read_payouts` scopes. The token doesn't expire.""",
            iconPath="/static/services/reverb.png",
            docsUrl="https://posthog.com/docs/cdp/sources/reverb",
            keywords=["marketplace", "musical instruments", "orders", "payouts"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="Personal access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.reverb.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized": "Your Reverb personal access token is invalid or has been revoked. Create a new token in your Reverb account settings, then reconnect.",
            "403 Client Error: Forbidden": "Your Reverb personal access token is missing the scopes needed to sync this data. Check the token's scopes, then reconnect.",
        }

    def get_schemas(
        self,
        config: ReverbSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: ReverbSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        ok, status_code = validate_reverb_credentials(config.api_token, self.resolve_api_version(api_version))
        if ok:
            return True, None
        if status_code == 401:
            return False, "Invalid Reverb personal access token"
        return False, "Could not connect to Reverb with the provided personal access token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ReverbResumeConfig]:
        return ResumableSourceManager[ReverbResumeConfig](inputs, ReverbResumeConfig)

    def source_for_pipeline(
        self,
        config: ReverbSourceConfig,
        resumable_source_manager: ResumableSourceManager[ReverbResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return reverb_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            api_version=self.resolve_api_version(inputs.api_version),
        )
