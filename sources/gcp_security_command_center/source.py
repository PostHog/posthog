from typing import cast

from sources.gcp_security_command_center._config import GcpSecurityCommandCenterSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GcpSecurityCommandCenterSource(SimpleSource[GcpSecurityCommandCenterSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GCPSECURITYCOMMANDCENTER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GCPSECURITYCOMMANDCENTER,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Google Cloud (Security Command Center)",
            iconPath="/static/services/gcp_security_command_center.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
