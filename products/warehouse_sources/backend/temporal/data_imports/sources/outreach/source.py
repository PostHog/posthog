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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.outreach import (
    OutreachSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.outreach.outreach import (
    OutreachResumeConfig,
    outreach_source,
    validate_credentials as validate_outreach_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.outreach.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class OutreachSource(ResumableSource[OutreachSourceConfig, OutreachResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog, safe for public docs
    api_docs_url = "https://developers.outreach.io/api/making-requests"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.OUTREACH

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.outreach.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "400 Client Error: Bad Request for url: https://api.outreach.io/oauth/token": "Outreach authentication failed. Your refresh token may be invalid or revoked. Please generate a new one.",
            "401 Client Error: Unauthorized for url: https://api.outreach.io/oauth/token": "Outreach authentication failed. Please check your OAuth app's client ID and client secret.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.OUTREACH,
            category=DataWarehouseSourceCategory.SALES,
            label="Outreach",
            caption="""Connect your Outreach account to pull prospects, accounts, sequences, and engagement data into the PostHog Data warehouse.

Outreach's API is OAuth-only, and its refresh tokens expire after 14 days. This source is not ready to connect yet, because it needs a PostHog-registered Outreach application to hold a credential that renews itself.""",
            iconPath="/static/services/outreach.png",
            docsUrl="https://posthog.com/docs/cdp/sources/outreach",
            releaseStatus=ReleaseStatus.ALPHA,
            # Outreach issues a new refresh token on every token exchange, invalidates the previous
            # one, and expires them after 14 days. A refresh token pasted into a form field can't be
            # written back, and each schema syncs in its own workflow, so parallel syncs would race
            # to spend the same token. Both need a credential PostHog owns and can update: either a
            # registered OAuth app or Outreach's server-to-server app tokens. Keep the source out of
            # the catalog until one of those is in place.
            unreleasedSource=True,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="client_id",
                        label="Client ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="client_secret",
                        label="Client secret",
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
        config: OutreachSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: OutreachSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_outreach_credentials(config.client_id, config.client_secret, config.refresh_token):
            return True, None

        return False, "Invalid Outreach credentials"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[OutreachResumeConfig]:
        return ResumableSourceManager[OutreachResumeConfig](inputs, OutreachResumeConfig)

    def source_for_pipeline(
        self,
        config: OutreachSourceConfig,
        resumable_source_manager: ResumableSourceManager[OutreachResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return outreach_source(
            client_id=config.client_id,
            client_secret=config.client_secret,
            refresh_token=config.refresh_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
