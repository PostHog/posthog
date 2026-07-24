from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gcpcomputeengine import (
    GcpComputeEngineSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GcpComputeEngineSource(SimpleSource[GcpComputeEngineSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GCPCOMPUTEENGINE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GCP_COMPUTE_ENGINE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Google Cloud Platform (Compute Engine)",
            iconPath="/static/services/gcp_compute_engine.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
