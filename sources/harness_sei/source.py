from typing import cast

from sources.harness_sei._config import HarnessSeiSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class HarnessSeiSource(SimpleSource[HarnessSeiSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HARNESSSEI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.HARNESSSEI,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Harness (Software Engineering Insights / SEI, formerly Propelo)",
            iconPath="/static/services/harness_sei.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
