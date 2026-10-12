from typing import cast

from sources.open_dental._config import OpenDentalSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class OpenDentalSource(SimpleSource[OpenDentalSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.OPENDENTAL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.OPENDENTAL,
            category=DataWarehouseSourceCategory.CRM,
            label="Open Dental",
            iconPath="/static/services/open_dental.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
