from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.msg91 import MSG91SourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MSG91Source(SimpleSource[MSG91SourceConfig]):
    api_docs_url = "https://docs.msg91.com/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MSG91

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MSG91,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="MSG91",
            iconPath="/static/services/msg91.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
