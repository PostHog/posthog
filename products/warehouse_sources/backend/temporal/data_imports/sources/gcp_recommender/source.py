from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.gcprecommender import (
    GcpRecommenderSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GcpRecommenderSource(SimpleSource[GcpRecommenderSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GCPRECOMMENDER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GCP_RECOMMENDER,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Google Cloud Platform (Recommender / Active Assist)",
            iconPath="/static/services/gcp_recommender.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
