from typing import cast

from sources.pennylane._config import PennylaneSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class PennylaneSource(SimpleSource[PennylaneSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PENNYLANE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.PENNYLANE,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Pennylane",
            iconPath="/static/services/pennylane.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
