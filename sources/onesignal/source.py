from typing import cast

from sources.onesignal._config import OneSignalSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class OneSignalSource(SimpleSource[OneSignalSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ONESIGNAL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ONESIGNAL,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="OneSignal",
            iconPath="/static/services/onesignal.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
