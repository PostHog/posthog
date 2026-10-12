from typing import cast

from sources.paylocity._config import PaylocitySourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class PaylocitySource(SimpleSource[PaylocitySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PAYLOCITY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.PAYLOCITY,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="Paylocity",
            iconPath="/static/services/paylocity.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
