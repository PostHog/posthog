from typing import cast

from sources.firebolt._config import FireboltSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class FireboltSource(SimpleSource[FireboltSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FIREBOLT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.FIREBOLT,
            category=DataWarehouseSourceCategory.DATABASES,
            keywords=["sql"],
            label="Firebolt",
            iconPath="/static/services/firebolt.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
