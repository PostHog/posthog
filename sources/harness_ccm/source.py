from typing import cast

from sources.harness_ccm._config import HarnessCcmSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class HarnessCcmSource(SimpleSource[HarnessCcmSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HARNESSCCM

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.HARNESSCCM,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Harness",
            iconPath="/static/services/harness_ccm.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
