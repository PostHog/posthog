from typing import cast

from sources.feishu._config import FeishuSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class FeishuSource(SimpleSource[FeishuSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FEISHU

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.FEISHU,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Feishu",
            iconPath="/static/services/feishu.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
