from typing import cast

from products.warehouse_sources.backend.facade.codebase_detection import NOT_DETECTABLE
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.azure_log_analytics.azure_log_analytics import (
    AzureLogAnalyticsResumeConfig,
    WorkspaceCredentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.azure_log_analytics.source import (
    WORKSPACE_FIELDS,
    LogAnalyticsWorkspaceSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.azureapimanagement import (
    AzureApiManagementSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

# The resource-specific tables API Management writes when its diagnostic setting sends logs to a
# Log Analytics workspace.
API_MANAGEMENT_TABLES = [
    "ApiManagementGatewayLogs",
    "ApiManagementGatewayLlmLog",
    "ApiManagementWebSocketConnectionLogs",
]


@SourceRegistry.register
class AzureApiManagementSource(LogAnalyticsWorkspaceSource[AzureApiManagementSourceConfig]):
    # Applications call an API Management gateway over plain HTTP, so no package or key names it.
    codebase_detection = NOT_DETECTABLE

    lists_tables_without_credentials = True
    api_docs_url = "https://learn.microsoft.com/en-us/azure/api-management/monitor-api-management"

    # A table is missing when its log category is not turned on, not because of a typo.
    missing_table_reason = (
        "No logs for this table yet. Turn on its log category in the API Management diagnostic setting."
    )
    missing_table_message = (
        "The workspace has no {table} logs yet. Turn on its log category in the API Management diagnostic setting."
    )
    no_tables_message = (
        "This workspace has no API Management logs. Check that the diagnostic setting sends logs to this "
        "workspace with Resource specific tables."
    )

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AZUREAPIMANAGEMENT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AZUREAPIMANAGEMENT,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Microsoft Azure API Management",
            keywords=["apim", "api gateway", "ai gateway"],
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Sync Azure API Management gateway logs into the PostHog Data warehouse: requests, LLM token usage, and WebSocket connections.

API Management must send its logs to a Log Analytics workspace. In the API Management instance, add a diagnostic setting that sends the `GatewayLogs`, `GatewayLlmLogs` and `WebSocketConnectionLogs` categories to the workspace, with **Resource specific** as the destination table.

Register an app in Microsoft Entra ID, create a client secret for it, and give its service principal the **Log Analytics Reader** role on the workspace. Then enter the directory (tenant) ID, the application (client) ID, the secret value, and the workspace ID from the workspace's **Overview** page.""",
            iconPath="/static/services/azure_api_management.png",
            docsUrl="https://posthog.com/docs/cdp/sources/azure-api-management",
            fields=cast(list[FieldType], WORKSPACE_FIELDS),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.azure_api_management.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def credentials(self, config: AzureApiManagementSourceConfig) -> WorkspaceCredentials:
        return WorkspaceCredentials(
            tenant_id=config.tenant_id,
            client_id=config.client_id,
            client_secret=config.client_secret,
            workspace_id=config.workspace_id,
        )

    def table_names(self, config: AzureApiManagementSourceConfig) -> list[str]:
        return API_MANAGEMENT_TABLES

    def tables_checked_at_creation(self, config: AzureApiManagementSourceConfig) -> list[str]:
        return API_MANAGEMENT_TABLES

    def source_for_pipeline(
        self,
        config: AzureApiManagementSourceConfig,
        resumable_source_manager: ResumableSourceManager[AzureLogAnalyticsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in API_MANAGEMENT_TABLES:
            raise ValueError(f"Unknown Azure API Management schema '{inputs.schema_name}'")
        return super().source_for_pipeline(config, resumable_source_manager, inputs)
