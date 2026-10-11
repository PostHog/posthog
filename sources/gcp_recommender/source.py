from typing import cast

from sources.gcp_recommender._config import GcpRecommenderSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class GcpRecommenderSource(SimpleSource[GcpRecommenderSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GCPRECOMMENDER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GCPRECOMMENDER,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Google Cloud Platform (Recommender / Active Assist)",
            iconPath="/static/services/gcp_recommender.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
