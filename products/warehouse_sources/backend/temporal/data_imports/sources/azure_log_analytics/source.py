from abc import abstractmethod
from typing import Generic, Optional, cast

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
    CREATION_PROBE_BUDGET_SECONDS,
    AzureLogAnalyticsResumeConfig,
    WorkspaceCredentials,
    azure_log_analytics_source,
    discover_tables,
    parse_table_names,
    probe_tables,
    validate_workspace,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.azure_log_analytics.settings import (
    INCREMENTAL_FIELDS,
    INGESTION_LOOKBACK_SECONDS,
    TABLE_NAME_RE,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    ConfigType,
    FieldType,
    ResumableSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.azureloganalytics import (
    AzureLogAnalyticsSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

WORKSPACE_FIELDS: list[FieldType] = [
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
]


class LogAnalyticsWorkspaceSource(ResumableSource[ConfigType, AzureLogAnalyticsResumeConfig], Generic[ConfigType]):
    """A source that syncs tables of one Log Analytics workspace. Subclasses pick the tables."""

    missing_table_reason = (
        "This table doesn't exist in the workspace. Check the table name, or remove it from the list."
    )
    missing_table_message = (
        "The workspace has no table named {table}. Check the table name, or remove it from the list."
    )
    no_tables_message = "None of the listed tables exist in the workspace. Check the table names."

    @abstractmethod
    def credentials(self, config: ConfigType) -> WorkspaceCredentials: ...

    @abstractmethod
    def table_names(self, config: ConfigType) -> list[str]: ...

    def tables_checked_at_creation(self, config: ConfigType) -> list[str]:
        """Tables probed at source creation; creation fails when every one of them is missing."""
        return []

    @property
    def connection_host_fields(self) -> list[str]:
        # `tenant_id` picks the directory the stored secret is exchanged in, and `workspace_id` picks
        # the workspace the token is spent on. Retargeting either must re-require the secret.
        return ["tenant_id", "workspace_id"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "400 Client Error: Bad Request for url: https://login.microsoftonline.com": "Microsoft Entra ID rejected the app credentials. Check the tenant ID, client ID and client secret, then reconnect.",
            "401 Client Error: Unauthorized for url: https://login.microsoftonline.com": "Microsoft Entra ID rejected the app credentials. Check the client ID and client secret, then reconnect.",
            "403 Client Error: Forbidden for url: https://login.microsoftonline.com": "Microsoft Entra ID refused to issue a token for the app. Check that the app registration can sign in to this tenant, then reconnect.",
            "401 Client Error: Unauthorized for url: https://api.loganalytics.azure.com": "Log Analytics rejected the access token. Check that the app registration is still enabled, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.loganalytics.azure.com": "The app cannot query this workspace. Give its service principal the Log Analytics Reader role on the workspace, or read access to the table, then reconnect.",
            "404 Client Error: Not Found for url: https://api.loganalytics.azure.com": "No Log Analytics workspace has this workspace ID. Check the workspace ID, then reconnect.",
            "Failed to resolve table": self.missing_table_reason,
        }

    def get_retryable_errors(self) -> set[str]:
        return {"Azure Log Analytics error (retryable)"}

    def get_schemas(
        self,
        config: ConfigType,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=table_name,
                supports_incremental=True,
                # The watermark re-reads a short overlap, which only merge dedupes.
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS,
                default_incremental_lookback_seconds=INGESTION_LOOKBACK_SECONDS,
            )
            for table_name in self.table_names(config)
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def get_endpoint_permissions(
        self,
        config: ConfigType,
        team_id: int,
        endpoints: list[str],
        api_version: str | None = None,
    ) -> dict[str, str | None]:
        return probe_tables(self.credentials(config), endpoints, self.missing_table_reason)

    def validate_credentials(
        self,
        config: ConfigType,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if schema_name is not None:
            if not TABLE_NAME_RE.match(schema_name):
                return False, f"{schema_name!r} is not a valid Log Analytics table name."
            return validate_workspace(
                self.credentials(config),
                f"{schema_name} | take 0",
                self.missing_table_message.format(table=schema_name),
            )
        try:
            tables = self.tables_checked_at_creation(config)
        except ValueError as error:
            return False, str(error)
        valid, message = validate_workspace(self.credentials(config), "print ok = 1", self.no_tables_message)
        if not valid or not tables:
            return valid, message
        # One query per table, stopping at the first readable one: a Basic plan table fails any
        # query that names it, and must not block the rest.
        reasons = probe_tables(
            self.credentials(config),
            tables,
            self.missing_table_reason,
            stop_at_first_readable=True,
            budget_seconds=CREATION_PROBE_BUDGET_SECONDS,
        )
        if any(reason is None for reason in reasons.values()):
            return True, None
        if all(reason == self.missing_table_reason for reason in reasons.values()):
            return False, self.no_tables_message
        first_reason = next(reason for reason in reasons.values() if reason != self.missing_table_reason)
        return False, f"None of the listed tables can be read. {first_reason}"

    def get_resumable_source_manager(
        self, inputs: SourceInputs
    ) -> ResumableSourceManager[AzureLogAnalyticsResumeConfig]:
        return ResumableSourceManager[AzureLogAnalyticsResumeConfig](inputs, AzureLogAnalyticsResumeConfig)

    def source_for_pipeline(
        self,
        config: ConfigType,
        resumable_source_manager: ResumableSourceManager[AzureLogAnalyticsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return azure_log_analytics_source(
            credentials=self.credentials(config),
            table=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )


@SourceRegistry.register
class AzureLogAnalyticsSource(LogAnalyticsWorkspaceSource[AzureLogAnalyticsSourceConfig]):
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
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AZURELOGANALYTICS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Microsoft Azure (Azure Monitor / Log Analytics)",
            keywords=["azure monitor", "log analytics", "kql"],
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Sync tables from an Azure Monitor Log Analytics workspace into the PostHog Data warehouse. Each table becomes a warehouse table, synced incrementally on the time Azure ingested each record, so records that arrive late still sync.

Register an app in Microsoft Entra ID, create a client secret for it, and give its service principal the **Log Analytics Reader** role on the workspace. Then enter the directory (tenant) ID, the application (client) ID, the secret value, and the workspace ID from the workspace's **Overview** page.

List the tables to sync, one per line, for example `AppRequests` or `MyEvents_CL`. Leave the list empty to offer every table that received data in the last 30 days.""",
            iconPath="/static/services/azure_log_analytics.png",
            docsUrl="https://posthog.com/docs/cdp/sources/azure-log-analytics",
            fields=cast(
                list[FieldType],
                [
                    *WORKSPACE_FIELDS,
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

    def credentials(self, config: AzureLogAnalyticsSourceConfig) -> WorkspaceCredentials:
        return WorkspaceCredentials(
            tenant_id=config.tenant_id,
            client_id=config.client_id,
            client_secret=config.client_secret,
            workspace_id=config.workspace_id,
        )

    def table_names(self, config: AzureLogAnalyticsSourceConfig) -> list[str]:
        # Discovery runs inside the source setup request, so it uses the short probe deadlines.
        return parse_table_names(config.tables) or discover_tables(
            self.credentials(config).client(structlog.get_logger(__name__), probe=True)
        )

    def tables_checked_at_creation(self, config: AzureLogAnalyticsSourceConfig) -> list[str]:
        return parse_table_names(config.tables)
