from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.smartrecruiters._config import SmartrecruitersSourceConfig


@SourceRegistry.register
class SmartrecruitersSource(SimpleSource[SmartrecruitersSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SMARTRECRUITERS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SMARTRECRUITERS,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="SmartRecruiters",
            iconPath="/static/services/smartrecruiters.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
