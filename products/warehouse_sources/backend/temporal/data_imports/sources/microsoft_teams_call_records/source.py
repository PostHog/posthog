from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.microsoftteamscallrecords import (
    MicrosoftTeamsCallRecordsSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MicrosoftTeamsCallRecordsSource(SimpleSource[MicrosoftTeamsCallRecordsSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MICROSOFTTEAMSCALLRECORDS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MICROSOFT_TEAMS_CALL_RECORDS,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Microsoft (Microsoft Graph / Teams)",
            iconPath="/static/services/microsoft_teams_call_records.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
