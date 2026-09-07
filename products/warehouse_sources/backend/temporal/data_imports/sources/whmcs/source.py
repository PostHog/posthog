from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.whmcs import WHMCSSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class WHMCSSource(SimpleSource[WHMCSSourceConfig]):
    api_docs_url = "https://developers.whmcs.com/api/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WHMCS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.WHMCS,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="WHMCS",
            iconPath="/static/services/whmcs.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
