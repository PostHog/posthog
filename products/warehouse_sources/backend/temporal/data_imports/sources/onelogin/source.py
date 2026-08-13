from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.onelogin import (
    OneloginSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class OneloginSource(SimpleSource[OneloginSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ONELOGIN

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ONELOGIN,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="OneLogin (One Identity / Quest Software)",
            iconPath="/static/services/onelogin.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
