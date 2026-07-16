from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import KickscaleSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class KickscaleSource(SimpleSource[KickscaleSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.KICKSCALE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.KICKSCALE,
            category=DataWarehouseSourceCategory.SALES,
            label="Kickscale",
            iconPath="/static/services/kickscale.png",
            keywords=["revenue intelligence", "sales enablement", "conversation intelligence"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
