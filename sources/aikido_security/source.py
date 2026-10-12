from typing import cast

from sources.aikido_security._config import AikidoSecuritySourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AikidoSecuritySource(SimpleSource[AikidoSecuritySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AIKIDOSECURITY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AIKIDOSECURITY,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Aikido Security",
            iconPath="/static/services/aikido_security.png",
            keywords=["security", "devsecops", "vulnerabilities", "appsec"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
