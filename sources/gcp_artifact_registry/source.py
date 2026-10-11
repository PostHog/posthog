from typing import cast

from sources.gcp_artifact_registry._config import GcpArtifactRegistrySourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GcpArtifactRegistrySource(SimpleSource[GcpArtifactRegistrySourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GCPARTIFACTREGISTRY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GCPARTIFACTREGISTRY,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Google Cloud (Artifact Registry)",
            iconPath="/static/services/gcp_artifact_registry.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
