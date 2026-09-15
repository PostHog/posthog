from typing import cast

from products.warehouse_sources.backend.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.mastodon import (
    MastodonSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MastodonSource(SimpleSource[MastodonSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MASTODON

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MASTODON,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Mastodon gGmbH (Mastodon)",
            iconPath="/static/services/mastodon.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
