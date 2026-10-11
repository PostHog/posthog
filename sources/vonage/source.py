from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.vonage._config import VonageSourceConfig


@SourceRegistry.register
class VonageSource(SimpleSource[VonageSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.VONAGE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.VONAGE,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Vonage (formerly Nexmo)",
            iconPath="/static/services/vonage.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
