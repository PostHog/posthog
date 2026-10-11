from typing import cast

from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)
from sources.zitadel._config import ZitadelSourceConfig


@SourceRegistry.register
class ZitadelSource(SimpleSource[ZitadelSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ZITADEL

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ZITADEL,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Zitadel",
            iconPath="/static/services/zitadel.png",
            keywords=["identity", "auth", "sso"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
