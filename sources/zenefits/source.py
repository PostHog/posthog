from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.zenefits._config import ZenefitsSourceConfig


@SourceRegistry.register
class ZenefitsSource(SimpleSource[ZenefitsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ZENEFITS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ZENEFITS,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="Zenefits",
            iconPath="/static/services/zenefits.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
