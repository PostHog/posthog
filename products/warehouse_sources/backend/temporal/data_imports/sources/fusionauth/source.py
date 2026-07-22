from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.fusionauth import (
    FusionAuthSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class FusionAuthSource(SimpleSource[FusionAuthSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FUSIONAUTH

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FUSION_AUTH,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="FusionAuth",
            iconPath="/static/services/fusionauth.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
