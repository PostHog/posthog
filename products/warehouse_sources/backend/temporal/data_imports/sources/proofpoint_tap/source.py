from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.proofpointtap import (
    ProofpointTapSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ProofpointTapSource(SimpleSource[ProofpointTapSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PROOFPOINTTAP

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.PROOFPOINTTAP,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Proofpoint, Inc. (Targeted Attack Protection)",
            iconPath="/static/services/proofpoint_tap.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
