from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CratesIOSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CratesIOSource(SimpleSource[CratesIOSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CRATESIO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CRATES_IO,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="crates.io (Rust Foundation / rust-lang)",
            iconPath="/static/services/crates_io.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
