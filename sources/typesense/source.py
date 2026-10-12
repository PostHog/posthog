from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.typesense._config import TypesenseSourceConfig


@SourceRegistry.register
class TypesenseSource(SimpleSource[TypesenseSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TYPESENSE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.TYPESENSE,
            category=DataWarehouseSourceCategory.DATABASES,
            label="Typesense",
            iconPath="/static/services/typesense.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
