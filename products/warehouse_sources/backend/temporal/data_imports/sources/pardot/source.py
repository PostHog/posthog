from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthConfig,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import OAuthMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
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
class PardotSource(ResumableSource[PardotSourceConfig, PardotResumeConfig], OAuthMixin):
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
            # SalesforceAuthRequestError formats a failed token refresh as
            # "<code> Client Error: <reason>: <error_description>", so key off the stable
            # error_description Salesforce returns for a revoked or expired grant.
            "expired access/refresh token": "Your Account Engagement connection has expired or been revoked. Please reconnect the source.",
            "inactive user": "The Salesforce user for this connection is inactive. Reactivate it in Salesforce or reconnect the source with an active user.",
            "Integration not found": "The linked Account Engagement integration no longer exists. Please reconnect the source.",
            "401 Client Error: Unauthorized for url": "Account Engagement rejected the access token. Please reconnect the source.",
            "403 Client Error: Forbidden for url": "Account Engagement denied access. Check that the connected user has API access and that the business unit ID is correct.",
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

Connect a Salesforce account that has access to Account Engagement, then enter the ID of the business unit you want to sync.""",
            iconPath="/static/services/pardot.png",
            docsUrl="https://posthog.com/docs/cdp/sources/pardot",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldOauthConfig(
                        name="pardot_integration_id",
                        label="Salesforce account",
                        required=True,
                        kind="pardot",
                        requiredScopes="pardot_api refresh_token",
                    ),
                    SourceFieldSelectConfig(
                        name="environment",
                        label="Environment",
                        required=True,
                        defaultValue="production",
                        caption="Choose sandbox if your business unit belongs to a sandbox, demo or developer org.",
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
                        caption="The 18-character ID starting with `0Uv`, in Salesforce Setup under Account Engagement Business Unit Setup.",
                        secret=False,
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
        try:
            integration = self.get_oauth_integration(config.pardot_integration_id, team_id)
        except ValueError:
            return False, "Connect a Salesforce account with access to Account Engagement"

        if not integration.access_token:
            return False, "The Salesforce connection has no access token. Please reconnect it."

        return validate_pardot_credentials(
            environment=config.environment,
            business_unit_id=config.business_unit_id,
            access_token=integration.access_token,
            refresh_token=integration.refresh_token,
            instance_url=integration.config.get("instance_url"),
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
        integration = self.get_oauth_integration(config.pardot_integration_id, inputs.team_id)

        if not integration.access_token:
            raise ValueError(f"Account Engagement access token not found for job {inputs.job_id}")

        return pardot_source(
            environment=config.environment,
            business_unit_id=config.business_unit_id,
            access_token=integration.access_token,
            refresh_token=integration.refresh_token,
            instance_url=integration.config.get("instance_url"),
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
