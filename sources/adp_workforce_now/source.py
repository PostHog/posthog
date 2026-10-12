from typing import cast

from sources.adp_workforce_now._config import AdpWorkforceNowSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class AdpWorkforceNowSource(SimpleSource[AdpWorkforceNowSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ADPWORKFORCENOW

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ADPWORKFORCENOW,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            keywords=["adp"],
            label="ADP Workforce Now",
            iconPath="/static/services/adp_workforce_now.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
