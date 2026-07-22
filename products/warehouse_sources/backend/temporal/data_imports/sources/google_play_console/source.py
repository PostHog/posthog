from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.googleplayconsole import (
    GooglePlayConsoleSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GooglePlayConsoleSource(SimpleSource[GooglePlayConsoleSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOOGLEPLAYCONSOLE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GOOGLE_PLAY_CONSOLE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Google Play Console (Play Developer Reporting API)",
            iconPath="/static/services/google_play_console.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
