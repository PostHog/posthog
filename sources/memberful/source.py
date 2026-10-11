from typing import cast

from sources.memberful._config import MemberfulSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class MemberfulSource(SimpleSource[MemberfulSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MEMBERFUL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.MEMBERFUL,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Memberful (Patreon, Inc.)",
            iconPath="/static/services/memberful.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
