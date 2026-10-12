from typing import cast

from sources.gcp_dataproc._config import GcpDataprocSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GcpDataprocSource(SimpleSource[GcpDataprocSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GCPDATAPROC

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GCPDATAPROC,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Google Cloud (Dataproc)",
            iconPath="/static/services/gcp_dataproc.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
