from typing import cast

from sources.mastodon._config import MastodonSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


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
