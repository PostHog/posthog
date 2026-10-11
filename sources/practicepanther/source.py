from typing import cast

from sources.practicepanther._config import PracticepantherSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class PracticepantherSource(SimpleSource[PracticepantherSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PRACTICEPANTHER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.PRACTICEPANTHER,
            category=DataWarehouseSourceCategory.CRM,
            label="PracticePanther",
            iconPath="/static/services/practicepanther.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
