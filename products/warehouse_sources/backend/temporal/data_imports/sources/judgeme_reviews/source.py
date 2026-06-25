from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import (
    JudgeMeReviewsSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class JudgeMeReviewsSource(SimpleSource[JudgeMeReviewsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.JUDGEMEREVIEWS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.JUDGE_ME_REVIEWS,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Judge.me Reviews",
            iconPath="/static/services/judgeme_reviews.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
