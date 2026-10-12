from typing import cast

from sources.gcp_chronicle._config import GcpChronicleSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GcpChronicleSource(SimpleSource[GcpChronicleSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GCPCHRONICLE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GCPCHRONICLE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Google Cloud (Chronicle / Google Security Operations)",
            iconPath="/static/services/gcp_chronicle.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
