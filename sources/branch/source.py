from typing import cast

from sources.branch._config import BranchSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class BranchSource(SimpleSource[BranchSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BRANCH

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.BRANCH,
            category=DataWarehouseSourceCategory.ADVERTISING,
            label="Branch",
            iconPath="/static/services/branch.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
