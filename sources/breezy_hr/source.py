from typing import cast

from sources.breezy_hr._config import BreezyHRSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class BreezyHRSource(SimpleSource[BreezyHRSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BREEZYHR

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.BREEZYHR,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="Breezy HR",
            iconPath="/static/services/breezy_hr.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
