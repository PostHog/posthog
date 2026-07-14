from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import DigitalOceanSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class DigitalOceanSource(SimpleSource[DigitalOceanSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DIGITALOCEAN

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.DIGITAL_OCEAN,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="DigitalOcean",
            iconPath="/static/services/digitalocean.png",
            keywords=["cloud", "infrastructure", "droplets", "billing"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
