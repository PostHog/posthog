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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.powerbiadmin import (
    PowerBiAdminSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.power_bi_admin.power_bi_admin import (
    ADMIN_API_DENIED_ERROR,
    PowerBiAdminResumeConfig,
    power_bi_admin_source,
    validate_credentials as validate_power_bi_admin_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.power_bi_admin.settings import (
    ACTIVITY_EVENTS_RETENTION_DAYS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    POWER_BI_ADMIN_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PowerBiAdminSource(ResumableSource[PowerBiAdminSourceConfig, PowerBiAdminResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # `v1.0` is a fixed segment of the admin API base path, not a version the tenant chooses.
    api_docs_url = "https://learn.microsoft.com/en-us/rest/api/power-bi/admin"

    @property
    def connection_host_fields(self) -> list[str]:
        # `tenant_id` selects which Entra directory the service principal's credentials are
        # sent to. Without listing it here, an editor could repoint a preserved client_secret
        # at a different tenant the same multi-tenant app registration happens to be in.
        return ["tenant_id"]

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.POWERBIADMIN

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            ADMIN_API_DENIED_ERROR: None,
            "400 Client Error: Bad Request for url: https://login.microsoftonline.com": (
                "Entra ID rejected the service principal. Check the tenant ID, application (client) ID, "
                "and client secret."
            ),
            "401 Client Error: Unauthorized for url: https://login.microsoftonline.com": (
                "Entra ID rejected the service principal credentials. Generate a new client secret and reconnect."
            ),
            "401 Client Error: Unauthorized for url: https://api.powerbi.com": ADMIN_API_DENIED_ERROR,
            "403 Client Error: Forbidden for url: https://api.powerbi.com": ADMIN_API_DENIED_ERROR,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.power_bi_admin.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: PowerBiAdminSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Only activity events carry a server-side time filter; the AsAdmin inventory lists
        # have no updated-since parameter, so they stay full refresh.
        return build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            descriptions={name: endpoint.description for name, endpoint in POWER_BI_ADMIN_ENDPOINTS.items()},
        )

    def validate_credentials(
        self,
        config: PowerBiAdminSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_power_bi_admin_credentials(
            tenant_id=config.tenant_id,
            client_id=config.client_id,
            client_secret=config.client_secret,
        )

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PowerBiAdminResumeConfig]:
        # Activity events persist a day/continuation cursor while inventory tables persist an
        # OData offset, so each endpoint keeps its state in its own Redis slot.
        return ResumableSourceManager[PowerBiAdminResumeConfig](inputs, PowerBiAdminResumeConfig).with_namespace(
            inputs.schema_name
        )

    def source_for_pipeline(
        self,
        config: PowerBiAdminSourceConfig,
        resumable_source_manager: ResumableSourceManager[PowerBiAdminResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return power_bi_admin_source(
            tenant_id=config.tenant_id,
            client_id=config.client_id,
            client_secret=config.client_secret,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.POWER_BI_ADMIN,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Power BI admin",
            keywords=["power bi", "powerbi", "fabric", "microsoft"],
            caption=(
                "Sync tenant-wide Power BI and Fabric governance data: the audit log of views, edits, exports "
                "and shares, plus the workspace, semantic model, report, dashboard, dataflow, and capacity "
                "inventories.\n\n"
                "Create an Entra ID app registration, add a client secret, and put the app in a security group "
                "that is allowed to use the read-only admin APIs in the Fabric admin portal. The app must not "
                "have any admin-consent Power BI permissions set on it. Then enter the directory (tenant) ID, "
                "application (client) ID, and client secret below.\n\n"
                f"Power BI only serves activity events for the last {ACTIVITY_EVENTS_RETENTION_DAYS} days, so the "
                "first sync starts there and everything after that builds up in your warehouse."
            ),
            docsUrl="https://posthog.com/docs/cdp/sources/power-bi-admin",
            iconPath="/static/services/power_bi_admin.png",
            releaseStatus=ReleaseStatus.ALPHA,
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
                ],
            ),
        )
