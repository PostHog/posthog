from typing import cast

from sources.oracle._config import OracleSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class OracleSource(SimpleSource[OracleSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ORACLE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ORACLE,
            category=DataWarehouseSourceCategory.DATABASES,
            keywords=["sql"],
            label="Oracle",
            iconPath="/static/services/oracle.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
