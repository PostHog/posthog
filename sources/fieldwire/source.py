from typing import cast

from sources.fieldwire._config import FieldwireSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class FieldwireSource(SimpleSource[FieldwireSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FIELDWIRE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.FIELDWIRE,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Fieldwire by Hilti",
            iconPath="/static/services/fieldwire.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
