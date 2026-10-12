from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.toast._config import ToastSourceConfig


@SourceRegistry.register
class ToastSource(SimpleSource[ToastSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TOAST

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.TOAST,
            category=DataWarehouseSourceCategory.SALES,
            label="Toast, Inc. (Toast POS)",
            iconPath="/static/services/toast.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
