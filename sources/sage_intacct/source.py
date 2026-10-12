from typing import cast

from sources.sage_intacct._config import SageIntacctSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class SageIntacctSource(SimpleSource[SageIntacctSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SAGEINTACCT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SAGEINTACCT,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Sage Intacct",
            iconPath="/static/services/sage_intacct.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
