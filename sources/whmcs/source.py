from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.whmcs._config import WHMCSSourceConfig


@SourceRegistry.register
class WHMCSSource(SimpleSource[WHMCSSourceConfig]):
    api_docs_url = "https://developers.whmcs.com/api/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WHMCS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.WHMCS,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="WHMCS",
            iconPath="/static/services/whmcs.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
