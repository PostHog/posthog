from typing import cast

from sources.curve._config import CurveSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class CurveSource(SimpleSource[CurveSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CURVE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CURVE,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Curve",
            iconPath="/static/services/curve.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
