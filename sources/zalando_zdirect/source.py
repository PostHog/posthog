from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.zalando_zdirect._config import ZalandoZdirectSourceConfig


@SourceRegistry.register
class ZalandoZdirectSource(SimpleSource[ZalandoZdirectSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ZALANDOZDIRECT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ZALANDOZDIRECT,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Zalando SE (zDirect Partner API)",
            iconPath="/static/services/zalando_zdirect.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
