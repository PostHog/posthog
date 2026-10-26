from typing import cast

from products.warehouse_sources.backend.facade.source_config import DataWarehouseSourceCategory, SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.beacons import (
    BeaconsSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BeaconsSource(SimpleSource[BeaconsSourceConfig]):
    api_docs_url = "https://help.beacons.ai/en/articles/11826369"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BEACONS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.BEACONS,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            keywords=["beacons.ai", "link in bio"],
            label="Beacons",
            iconPath="/static/services/beacons.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
