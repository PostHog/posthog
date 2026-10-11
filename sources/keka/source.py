from typing import cast

from sources.keka._config import KekaSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class KekaSource(SimpleSource[KekaSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.KEKA

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.KEKA,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="Keka",
            iconPath="/static/services/keka.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
