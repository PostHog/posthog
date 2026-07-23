from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ahaideas import (
    AhaIdeasSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AhaIdeasSource(SimpleSource[AhaIdeasSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AHAIDEAS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AHA_IDEAS,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Aha! (Aha! Labs Inc.)",
            iconPath="/static/services/aha_ideas.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
