from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.sumsub._config import SumsubSourceConfig


@SourceRegistry.register
class SumsubSource(SimpleSource[SumsubSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SUMSUB

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SUMSUB,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Sumsub",
            iconPath="/static/services/sumsub.png",
            keywords=["kyc", "identity verification", "aml", "compliance"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
