from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import KapaAISourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class KapaAISource(SimpleSource[KapaAISourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.KAPAAI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.KAPA_AI,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="kapa.ai",
            iconPath="/static/services/kapa_ai.png",
            keywords=["ai assistant", "docs", "support", "conversations"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
