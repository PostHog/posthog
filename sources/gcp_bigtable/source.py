from typing import cast

from sources.gcp_bigtable._config import GcpBigtableSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GcpBigtableSource(SimpleSource[GcpBigtableSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GCPBIGTABLE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GCPBIGTABLE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Google Cloud Platform",
            iconPath="/static/services/gcp_bigtable.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
