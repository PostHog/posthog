from typing import cast

from sources.employment_hero._config import EmploymentHeroSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class EmploymentHeroSource(SimpleSource[EmploymentHeroSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.EMPLOYMENTHERO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.EMPLOYMENTHERO,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="Employment-Hero",
            iconPath="/static/services/employment_hero.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
