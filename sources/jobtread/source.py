from typing import cast

from sources.jobtread._config import JobtreadSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class JobtreadSource(SimpleSource[JobtreadSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.JOBTREAD

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.JOBTREAD,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="JobTread",
            iconPath="/static/services/jobtread.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
