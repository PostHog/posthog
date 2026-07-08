from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import PyPISourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PyPISource(SimpleSource[PyPISourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PYPI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PY_PI,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="PyPI",
            iconPath="/static/services/pypi.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
