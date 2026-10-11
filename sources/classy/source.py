from typing import cast

from sources.classy._config import ClassySourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class ClassySource(SimpleSource[ClassySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CLASSY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CLASSY,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="GoFundMe Pro (Classy)",
            iconPath="/static/services/classy.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
