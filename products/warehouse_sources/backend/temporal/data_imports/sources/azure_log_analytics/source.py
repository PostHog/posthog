from typing import Optional, cast

import structlog

from products.warehouse_sources.backend.facade.codebase_detection import detect
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.azure_log_analytics.azure_log_analytics import (
    AzureLogAnalyticsClient,
    AzureLogAnalyticsResumeConfig,
    azure_log_analytics_source,
    discover_tables,
    parse_table_names,
    validate_credentials as validate_log_analytics_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.azure_log_analytics.settings import (
    INCREMENTAL_FIELDS,
    INGESTION_LOOKBACK_SECONDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.azureloganalytics import (
    AzureLogAnalyticsSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


def log_analytics_schemas(table_names: list[str]) -> list[SourceSchema]:
    return [
        SourceSchema(
            name=table_name,
            supports_incremental=True,
            supports_append=True,
            incremental_fields=INCREMENTAL_FIELDS,
            default_incremental_lookback_seconds=INGESTION_LOOKBACK_SECONDS,
        )
        for table_name in table_names
    ]


@SourceRegistry.register
class AzureLogAnalyticsSource(ResumableSource[AzureLogAnalyticsSourceConfig, AzureLogAnalyticsResumeConfig]):
    codebase_detection = detect(
        env=("^(AZURE_LOG_ANALYTICS|LOG_ANALYTICS)_",),
        npm=("@azure/monitor-query", "@azure/monitor-query-logs"),
        pypi=("azure-monitor-query",),
        go=("github.com/Azure/azure-sdk-for-go/sdk/monitor/query/azlogs",),
        maven=("com.azure:azure-monitor-query",),
    )

    api_docs_url = "https://learn.microsoft.com/en-us/azure/azure-monitor/logs/api/overview"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AZURELOGANALYTICS

    @property
    def connection_host_fields(self) -> list[str]:
        # `tenant_id` picks the directory the stored secret is exchanged in, and `workspace_id` picks
        # the workspace the token is spent on. Retargeting either must re-require the secret.
        return ["tenant_id", "workspace_id"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AZURELOGANALYTICS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Microsoft Azure (Azure Monitor / Log Analytics)",
            keywords=["azure monitor", "log analytics", "kql"],
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Sync tables from an Azure Monitor Log Analytics workspace into the PostHog Data warehouse. Each table becomes a warehouse table, synced incrementally on `TimeGenerated`.

Register an app in Microsoft Entra ID, create a client secret for it, and give its service principal the **Log Analytics Reader** role on the workspace. Then enter the directory (tenant) ID, the application (client) ID, the secret value, and the workspace ID from the workspace's **Overview** page.

List the tables to sync, one per line, for example `AppRequests` or `MyEvents_CL`. Leave the list empty to offer every table that received data in the last 30 days.""",
            iconPath="/static/services/azure_log_analytics.png",
            docsUrl="https://posthog.com/docs/cdp/sources/azure-log-analytics",
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
                        name="workspace_id",
                        label="Workspace ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="00000000-0000-0000-0000-000000000000",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="tables",
                        label="Tables",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=False,
                        placeholder="AppRequests\nAppExceptions\nMyEvents_CL",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "400 Client Error: Bad Request for url: https://login.microsoftonline.com": "Microsoft Entra ID rejected the app credentials. Check the tenant ID, client ID and client secret, then reconnect.",
            "401 Client Error: Unauthorized for url: https://login.microsoftonline.com": "Microsoft Entra ID rejected the app credentials. Check the client ID and client secret, then reconnect.",
            "401 Client Error: Unauthorized for url: https://api.loganalytics.azure.com": "Log Analytics rejected the access token. Check that the app registration is still enabled, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.loganalytics.azure.com": "The app cannot query this workspace. Give its service principal the Log Analytics Reader role on the workspace, then reconnect.",
            "404 Client Error: Not Found for url: https://api.loganalytics.azure.com": "No Log Analytics workspace has this workspace ID. Check the workspace ID, then reconnect.",
            "Failed to resolve table": "This table no longer exists in the workspace. Remove it from the source's table list.",
        }

    def get_retryable_errors(self) -> set[str]:
        return {"Azure Log Analytics error (retryable)"}

    def configured_table_names(self, config: AzureLogAnalyticsSourceConfig) -> list[str]:
        return parse_table_names(config.tables)

    def get_schemas(
        self,
        config: AzureLogAnalyticsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        table_names = self.configured_table_names(config)
        if not table_names:
            client = AzureLogAnalyticsClient(
                config.tenant_id,
                config.client_id,
                config.client_secret,
                config.workspace_id,
                structlog.get_logger(__name__),
            )
            table_names = discover_tables(client)

        schemas = log_analytics_schemas(table_names)
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: AzureLogAnalyticsSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            self.configured_table_names(config)
        except ValueError as error:
            return False, str(error)

        return validate_log_analytics_credentials(
            tenant_id=config.tenant_id,
            client_id=config.client_id,
            client_secret=config.client_secret,
            workspace_id=config.workspace_id,
            table=schema_name,
        )

    def get_resumable_source_manager(
        self, inputs: SourceInputs
    ) -> ResumableSourceManager[AzureLogAnalyticsResumeConfig]:
        return ResumableSourceManager[AzureLogAnalyticsResumeConfig](inputs, AzureLogAnalyticsResumeConfig)

    def source_for_pipeline(
        self,
        config: AzureLogAnalyticsSourceConfig,
        resumable_source_manager: ResumableSourceManager[AzureLogAnalyticsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return azure_log_analytics_source(
            tenant_id=config.tenant_id,
            client_id=config.client_id,
            client_secret=config.client_secret,
            workspace_id=config.workspace_id,
            table=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
