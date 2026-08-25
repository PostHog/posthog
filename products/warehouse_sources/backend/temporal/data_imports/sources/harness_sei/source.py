from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.harnesssei import (
    HarnessSeiSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class HarnessSeiSource(SimpleSource[HarnessSeiSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HARNESSSEI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.HARNESS_SEI,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Harness (Software Engineering Insights / SEI, formerly Propelo)",
            iconPath="/static/services/harness_sei.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
