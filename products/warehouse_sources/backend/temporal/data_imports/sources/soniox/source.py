from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.soniox import SonioxSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SonioxSource(SimpleSource[SonioxSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SONIOX

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SONIOX,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Soniox",
            iconPath="/static/services/soniox.png",
            keywords=["speech-to-text", "transcription"],
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
