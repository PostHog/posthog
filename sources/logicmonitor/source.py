from typing import cast

from sources.logicmonitor._config import LogicmonitorSourceConfig
from sources.logicmonitor.canonical_descriptions import CANONICAL_DESCRIPTIONS
from sources.logicmonitor.logicmonitor import (
    AUTH_ERROR,
    DENSE_WINDOW_ERROR,
    PERMISSION_ERROR,
    LogicMonitorClient,
    LogicMonitorResumeConfig,
    validate_portal_host,
)
from sources.logicmonitor.settings import API_DOCS_URL, API_VERSION, ENDPOINTS
from sources.sdk import (
    CanonicalDescriptions,
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    ReleaseStatus,
    ResumableSource,
    ResumableSourceManager,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceInputs,
    SourceRegistry,
    SourceResponse,
    SourceSchema,
    build_endpoint_schemas,
)


@SourceRegistry.register
class LogicmonitorSource(ResumableSource[LogicmonitorSourceConfig, LogicMonitorResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = (API_VERSION,)
    default_version = API_VERSION
    api_docs_url = API_DOCS_URL

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LOGICMONITOR

    @property
    def connection_host_fields(self) -> list[str]:
        return ["portal_url"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": AUTH_ERROR,
            "403 Client Error": PERMISSION_ERROR,
            DENSE_WINDOW_ERROR: DENSE_WINDOW_ERROR,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: LogicmonitorSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # A start-time watermark misses later acknowledgments and clear events for older alerts.
        return build_endpoint_schemas(ENDPOINTS, {}, names)

    def validate_credentials(
        self,
        config: LogicmonitorSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        valid, error = validate_portal_host(config.portal_url, team_id)
        if not valid:
            return False, error
        return LogicMonitorClient(config).validate_credentials()

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[LogicMonitorResumeConfig]:
        return ResumableSourceManager(inputs, LogicMonitorResumeConfig)

    def source_for_pipeline(
        self,
        config: LogicmonitorSourceConfig,
        resumable_source_manager: ResumableSourceManager[LogicMonitorResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        valid, error = validate_portal_host(config.portal_url, inputs.team_id)
        if not valid:
            raise ValueError(error)
        return LogicMonitorClient(config).source_response(inputs, resumable_source_manager)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.LOGICMONITOR,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="LogicMonitor",
            caption=(
                "Create a bearer token in Settings > Users & Roles > API Tokens > Bearer. "
                "Give its user view access to Resources, Dashboards, Collectors, and Websites for the tables you select. "
                "Alerts use full refresh to capture acknowledgments and cleared status."
            ),
            iconPath="/static/services/logicmonitor.png",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="portal_url",
                        label="Portal URL",
                        type=SourceFieldInputConfigType.TEXT,
                        placeholder="https://example.logicmonitor.com",
                        required=True,
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="bearer_token",
                        label="Bearer token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        placeholder="",
                        required=True,
                        secret=True,
                    ),
                ],
            ),
        )
