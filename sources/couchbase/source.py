from typing import cast

from sources.couchbase._config import CouchbaseSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class CouchbaseSource(SimpleSource[CouchbaseSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.COUCHBASE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.COUCHBASE,
            category=DataWarehouseSourceCategory.DATABASES,
            label="Couchbase",
            iconPath="/static/services/couchbase.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
