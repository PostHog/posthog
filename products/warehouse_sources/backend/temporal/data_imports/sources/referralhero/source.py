from typing import cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ReferralHeroSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ReferralHeroSource(SimpleSource[ReferralHeroSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.REFERRALHERO

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.REFERRAL_HERO,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="ReferralHero",
            iconPath="/static/services/referralhero.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
