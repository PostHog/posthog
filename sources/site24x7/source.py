from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.site24x7._config import Site24x7SourceConfig


@SourceRegistry.register
class Site24x7Source(SimpleSource[Site24x7SourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SITE24X7

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SITE24X7,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Site24x7 (Zoho Corporation)",
            iconPath="/static/services/site24x7.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
