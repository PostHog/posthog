from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.triple_whale._config import TripleWhaleSourceConfig


@SourceRegistry.register
class TripleWhaleSource(SimpleSource[TripleWhaleSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TRIPLEWHALE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.TRIPLEWHALE,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Triple Whale",
            iconPath="/static/services/triplewhale.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
