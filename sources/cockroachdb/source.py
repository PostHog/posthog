from typing import cast

from sources.cockroachdb._config import CockroachDBSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class CockroachDBSource(SimpleSource[CockroachDBSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.COCKROACHDB

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.COCKROACHDB,
            category=DataWarehouseSourceCategory.DATABASES,
            keywords=["sql"],
            label="CockroachDB",
            iconPath="/static/services/cockroachdb.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
