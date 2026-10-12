from typing import cast

from sources.msg91._config import MSG91SourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class MSG91Source(SimpleSource[MSG91SourceConfig]):
    api_docs_url = "https://docs.msg91.com/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MSG91

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MSG91,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="MSG91",
            iconPath="/static/services/msg91.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
