from typing import cast

from sources.procore._config import ProcoreSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class ProcoreSource(SimpleSource[ProcoreSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PROCORE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.PROCORE,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Procore Technologies",
            iconPath="/static/services/procore.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
