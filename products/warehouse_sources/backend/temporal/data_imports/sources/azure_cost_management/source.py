from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.azure_cost_management.azure_cost_management import (
    AzureCostManagementResumeConfig,
    azure_cost_management_source,
    validate_credentials as validate_azure_cost_management_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.azure_cost_management.settings import (
    AZURE_COST_MANAGEMENT_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.azurecostmanagement import (
    AzureCostManagementSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AzureCostManagementSource(ResumableSource[AzureCostManagementSourceConfig, AzureCostManagementResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # api-version is a required query param on every Cost Management call; the resolved pin flows
    # through verbatim to `_endpoint_url`. The query/forecast/dimensions wire is identical across
    # these versions (2026-06-01 only adds MarkupRules, which this source doesn't read), so no
    # per-version request branching is needed.
    supported_versions = ("2025-03-01", "2026-06-01")
    default_version = "2026-06-01"
    api_docs_url = "https://learn.microsoft.com/en-us/rest/api/cost-management/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AZURECOSTMANAGEMENT

    @property
    def connection_host_fields(self) -> list[str]:
        # `tenant_id` picks the Azure AD directory the stored client secret is exchanged against
        # (a multi-tenant app registration will mint a token in another directory), and `scope`
        # picks the ARM path the resulting token is spent on. Retargeting either would let an
        # editor point a preserved secret at a directory or subscription/billing account it wasn't
        # connected to, so both must force credential re-entry.
        return ["tenant_id", "scope"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AZURE_COST_MANAGEMENT,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Microsoft Azure Cost Management",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Pull your daily Azure spend into the PostHog Data warehouse, broken down by service, resource group, and resource.

Register an app in Microsoft Entra ID, create a client secret for it, and give its service principal the `Cost Management Reader` role on the scope you want to sync. Then enter the directory (tenant) ID, the application (client) ID, and the secret value.

The scope is the Azure Resource Manager path to read cost for, without a leading slash — for example `subscriptions/00000000-0000-0000-0000-000000000000` for one subscription, or `providers/Microsoft.Billing/billingAccounts/1234567` for an enterprise billing account.""",
            iconPath="/static/services/azure_cost_management.png",
            docsUrl="https://posthog.com/docs/cdp/sources/azure-cost-management",
            keywords=["azure", "finops", "cloud cost", "billing"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="tenant_id",
                        label="Directory (tenant) ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="00000000-0000-0000-0000-000000000000",
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
                    SourceFieldInputConfig(
                        name="scope",
                        label="Scope",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="subscriptions/00000000-0000-0000-0000-000000000000",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="start_date",
                        label="Start date (historical backfill)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="YYYY-MM-DD",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.azure_cost_management.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # A wrong tenant, client id, or expired secret fails the client-credentials exchange, and
            # no amount of retrying fixes a credential.
            "400 Client Error: Bad Request for url: https://login.microsoftonline.com": "Azure AD rejected the service principal credentials. Check the directory (tenant) ID, application (client) ID, and client secret, then reconnect.",
            "401 Client Error: Unauthorized for url: https://login.microsoftonline.com": "Azure AD rejected the service principal credentials. Check the application (client) ID and client secret, then reconnect.",
            "401 Client Error: Unauthorized for url: https://management.azure.com": "Azure rejected the access token for Cost Management. Check that the app registration is still enabled, then reconnect.",
            "403 Client Error: Forbidden for url: https://management.azure.com": "The service principal cannot read Cost Management on this scope. Give it the Cost Management Reader role on the scope, then reconnect.",
        }

    def get_retryable_errors(self) -> set[str]:
        return {"Azure Cost Management error (retryable)"}

    def get_schemas(
        self,
        config: AzureCostManagementSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint_config.name,
                supports_incremental=endpoint_config.supports_incremental,
                # Azure restates a day's cost after the fact, so append would materialize a second
                # row every time an already-imported day changes — these tables are merge-only.
                supports_append=False,
                incremental_fields=endpoint_config.incremental_fields,
                description=endpoint_config.description,
                default_incremental_lookback_seconds=endpoint_config.default_incremental_lookback_seconds,
            )
            for endpoint_config in AZURE_COST_MANAGEMENT_ENDPOINTS.values()
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self,
        config: AzureCostManagementSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_azure_cost_management_credentials(
            tenant_id=config.tenant_id,
            client_id=config.client_id,
            client_secret=config.client_secret,
            scope=config.scope,
            api_version=self.resolve_api_version(api_version),
        )

    def get_resumable_source_manager(
        self, inputs: SourceInputs
    ) -> ResumableSourceManager[AzureCostManagementResumeConfig]:
        return ResumableSourceManager[AzureCostManagementResumeConfig](inputs, AzureCostManagementResumeConfig)

    def source_for_pipeline(
        self,
        config: AzureCostManagementSourceConfig,
        resumable_source_manager: ResumableSourceManager[AzureCostManagementResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return azure_cost_management_source(
            tenant_id=config.tenant_id,
            client_id=config.client_id,
            client_secret=config.client_secret,
            scope=config.scope,
            endpoint=inputs.schema_name,
            start_date=config.start_date,
            api_version=self.resolve_api_version(inputs.api_version),
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
