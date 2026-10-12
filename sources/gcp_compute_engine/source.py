from typing import cast

from sources.gcp_compute_engine._config import GcpComputeEngineSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GcpComputeEngineSource(SimpleSource[GcpComputeEngineSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GCPCOMPUTEENGINE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GCPCOMPUTEENGINE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Google Cloud Platform (Compute Engine)",
            iconPath="/static/services/gcp_compute_engine.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
