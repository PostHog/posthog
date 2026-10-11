from typing import cast

from sources.google_workspace_admin_reports._config import GoogleWorkspaceAdminReportsSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GoogleWorkspaceAdminReportsSource(SimpleSource[GoogleWorkspaceAdminReportsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOOGLEWORKSPACEADMINREPORTS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GOOGLEWORKSPACEADMINREPORTS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Google Workspace Admin Reports",
            iconPath="/static/services/google_workspace_admin_reports.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
