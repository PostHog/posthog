from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.workato._config import WorkatoSourceConfig


@SourceRegistry.register
class WorkatoSource(SimpleSource[WorkatoSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WORKATO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.WORKATO,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Workato",
            iconPath="/static/services/workato.png",
            keywords=["ipaas", "automation", "integration"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
