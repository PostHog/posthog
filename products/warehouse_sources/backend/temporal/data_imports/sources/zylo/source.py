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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.zylo import ZyloSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.zylo.settings import ZYLO_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.zylo.zylo import (
    ZyloResumeConfig,
    probe_endpoint_status,
    validate_credentials as validate_zylo_credentials,
    zylo_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

# Scopes required per endpoint, surfaced in `get_endpoint_permissions` when a probe returns 403.
# https://developer.zylo.com/reference/permissions
_ENDPOINT_SCOPES: dict[str, str] = {
    "Applications": "applications:read",
    "ApplicationLicenses": "applications:read",
    "ApplicationUsers": "team:read",
    "Contracts": "contracts:read",
    "ContractLineItems": "contracts:read",
    "Payments": "spend:read",
    # Premium feature — needs both scopes.
    "PurchaseOrders": "applications:read and spend:read",
    "POLineItems": "applications:read and spend:read",
    "Suppliers": "contracts:read",
    "SavingsEvents": "applications:read",
    "ApplicationBudgets": "applications:read",
    "ActivityHistory": "team:read",
}


@SourceRegistry.register
class ZyloSource(ResumableSource[ZyloSourceConfig, ZyloResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://developer.zylo.com/reference"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ZYLO

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Zylo authentication failed. Please check your API token ID and secret.",
            "403 Client Error: Forbidden for url": "Your Zylo API key does not have the required permission scope for this resource.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.zylo.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: ZyloSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint_config.name,
                supports_incremental=len(endpoint_config.incremental_fields) > 0,
                supports_append=len(endpoint_config.incremental_fields) > 0,
                incremental_fields=endpoint_config.incremental_fields,
            )
            for endpoint_config in ZYLO_ENDPOINTS.values()
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def get_endpoint_permissions(
        self, config: ZyloSourceConfig, team_id: int, endpoints: list[str], api_version: str | None = None
    ) -> dict[str, str | None]:
        permissions: dict[str, str | None] = {}
        for endpoint in endpoints:
            endpoint_config = ZYLO_ENDPOINTS.get(endpoint)
            if endpoint_config is None:
                permissions[endpoint] = None
                continue
            status = probe_endpoint_status(config.token_id, config.token_secret, endpoint_config.path)
            # Only a real denial counts as missing scope — throttles, 5xx, and network blips
            # must not mark a table unreachable.
            if status == 403:
                scope = _ENDPOINT_SCOPES.get(endpoint, "the required")
                permissions[endpoint] = f"API key is missing the `{scope}` permission scope"
            elif status == 401:
                permissions[endpoint] = "API key is invalid"
            else:
                permissions[endpoint] = None
        return permissions

    def validate_credentials(
        self, config: ZyloSourceConfig, team_id: int, schema_name: Optional[str] = None, api_version: str | None = None
    ) -> tuple[bool, str | None]:
        if not config.token_id or not config.token_secret:
            return False, "Zylo token ID and token secret are required"

        if validate_zylo_credentials(config.token_id, config.token_secret):
            return True, None

        return False, "Invalid Zylo credentials"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ZyloResumeConfig]:
        return ResumableSourceManager[ZyloResumeConfig](inputs, ZyloResumeConfig)

    def source_for_pipeline(
        self,
        config: ZyloSourceConfig,
        resumable_source_manager: ResumableSourceManager[ZyloResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return zylo_source(
            token_id=config.token_id,
            token_secret=config.token_secret,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            incremental_field=inputs.incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ZYLO,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Zylo",
            keywords=["saas spend", "license management", "subscriptions", "it finance"],
            caption=(
                "Import your SaaS spend and license data from Zylo. Create an Enterprise API key under "
                "**Integrations → API Integration → Connect** in Zylo and paste the token ID and secret "
                "below. The key needs read scopes (e.g. `applications:read`, `contracts:read`, "
                "`spend:read`, `team:read`) for the resources you want to sync — Purchase Orders and PO "
                "Line Items are a premium feature and additionally require `spend:read`."
            ),
            iconPath="/static/services/zylo.png",
            docsUrl="https://posthog.com/docs/cdp/sources/zylo",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="token_id",
                        label="Token ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="token_secret",
                        label="Token secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )
