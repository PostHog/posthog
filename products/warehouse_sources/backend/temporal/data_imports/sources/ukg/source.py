from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ukg import UKGSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class UKGSource(SimpleSource[UKGSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.UKG

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.UKG,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="UKG",
            iconPath="/static/services/ukg.png",
            keywords=["ultimate kronos group", "ukg pro", "ukg ready", "workforce management"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
