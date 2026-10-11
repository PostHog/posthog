from typing import cast

from sources.oracle_ebs._config import OracleEbsSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class OracleEbsSource(SimpleSource[OracleEbsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ORACLEEBS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ORACLEEBS,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            keywords=["oracle e-business suite", "ebs"],
            label="Oracle EBS",
            iconPath="/static/services/oracle.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
