from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.signnow._config import SignNowSourceConfig


@SourceRegistry.register
class SignNowSource(SimpleSource[SignNowSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SIGNNOW

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SIGNNOW,
            category=DataWarehouseSourceCategory.SALES,
            label="SignNow",
            iconPath="/static/services/signnow.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
