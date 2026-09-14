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
from products.warehouse_sources.backend.temporal.data_imports.sources.dynamics_365_business_central.dynamics_365_business_central import (
    Dynamics365BusinessCentralResumeConfig,
    dynamics_365_business_central_source,
    validate_credentials as validate_business_central_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.dynamics_365_business_central.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.dynamics365businesscentral import (
    Dynamics365BusinessCentralSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class Dynamics365BusinessCentralSource(
    ResumableSource[Dynamics365BusinessCentralSourceConfig, Dynamics365BusinessCentralResumeConfig]
):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # Business Central versions its API in the request path (`/api/v2.0/`); v2.0 is the standard API
    # this source calls.
    supported_versions = ("v2.0",)
    default_version = "v2.0"
    api_docs_url = "https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/api-reference/v2.0/"

    @property
    def connection_host_fields(self) -> list[str]:
        return ["tenant_id", "environment"]

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DYNAMICS365BUSINESSCENTRAL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.DYNAMICS365_BUSINESS_CENTRAL,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Microsoft Dynamics 365 Business Central",
            caption="""Sync your Business Central customers, vendors, items, documents and general ledger entries into the PostHog Data warehouse.

Register an app in [Microsoft Entra ID](https://learn.microsoft.com/en-us/dynamics365/business-central/dev-itpro/administration/automation-apis-using-s2s-authentication) and grant it the `API.ReadWrite.All` application permission with admin consent, then add it as a Business Central user in the environment you want to sync. Enter that app's client ID and secret below, along with your Entra tenant ID and the environment name (usually `production`).

Every table except companies is synced for all companies in the environment, with the company ID kept on each row.""",
            iconPath="/static/services/dynamics_365_business_central.png",
            docsUrl="https://posthog.com/docs/cdp/sources/dynamics-365-business-central",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["business central", "dynamics 365", "erp", "microsoft", "bc"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="tenant_id",
                        label="Microsoft Entra tenant ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="00000000-0000-0000-0000-000000000000",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="environment",
                        label="Environment name",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="production",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="client_id",
                        label="Application (client) ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="00000000-0000-0000-0000-000000000000",
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
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.businesscentral.dynamics.com": "Business Central rejected the access token. Check that your Entra app is still added as a Business Central user in this environment.",
            "403 Client Error: Forbidden for url: https://api.businesscentral.dynamics.com": "Business Central denied access. Grant your Entra app the API.ReadWrite.All permission with admin consent.",
            "[oauth2_token_config_error]": "Microsoft Entra ID rejected the token request. Check your tenant ID, client ID and client secret — the secret may have expired.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.dynamics_365_business_central.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: Dynamics365BusinessCentralSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: Dynamics365BusinessCentralSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_business_central_credentials(
            tenant_id=config.tenant_id,
            environment=config.environment,
            client_id=config.client_id,
            client_secret=config.client_secret,
            api_version=self.resolve_api_version(api_version),
        )

    def get_resumable_source_manager(
        self, inputs: SourceInputs
    ) -> ResumableSourceManager[Dynamics365BusinessCentralResumeConfig]:
        return ResumableSourceManager[Dynamics365BusinessCentralResumeConfig](
            inputs, Dynamics365BusinessCentralResumeConfig
        )

    def source_for_pipeline(
        self,
        config: Dynamics365BusinessCentralSourceConfig,
        resumable_source_manager: ResumableSourceManager[Dynamics365BusinessCentralResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return dynamics_365_business_central_source(
            tenant_id=config.tenant_id,
            environment=config.environment,
            client_id=config.client_id,
            client_secret=config.client_secret,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            api_version=self.resolve_api_version(inputs.api_version),
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
