from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PackagistSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PackagistSource(SimpleSource[PackagistSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PACKAGIST

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PACKAGIST,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Packagist (packagist.org, operated by Packagist Conductors GmbH)",
            iconPath="/static/services/packagist.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
