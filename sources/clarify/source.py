from typing import cast

from sources.clarify._config import ClarifySourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class ClarifySource(SimpleSource[ClarifySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CLARIFY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CLARIFY,
            category=DataWarehouseSourceCategory.CRM,
            label="Clarify",
            iconPath="/static/services/clarify.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
