from typing import cast

from sources.gcp_container_analysis._config import GcpContainerAnalysisSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GcpContainerAnalysisSource(SimpleSource[GcpContainerAnalysisSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GCPCONTAINERANALYSIS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GCPCONTAINERANALYSIS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Google Cloud Container Analysis (Artifact Analysis)",
            iconPath="/static/services/gcp_container_analysis.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
