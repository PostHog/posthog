from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.snovio._config import SnovioSourceConfig


@SourceRegistry.register
class SnovioSource(SimpleSource[SnovioSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SNOVIO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SNOVIO,
            category=DataWarehouseSourceCategory.SALES,
            keywords=["snov.io", "email outreach", "lead generation"],
            label="Snov.io",
            iconPath="/static/services/snovio.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
