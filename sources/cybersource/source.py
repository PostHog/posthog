from typing import cast

from sources.cybersource._config import CybersourceSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class CybersourceSource(SimpleSource[CybersourceSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CYBERSOURCE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CYBERSOURCE,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Cybersource",
            iconPath="/static/services/cybersource.png",
            keywords=["payments", "visa"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
