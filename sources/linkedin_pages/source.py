from typing import cast

from sources.linkedin_pages._config import LinkedinPagesSourceConfig
from sources.sdk import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    SimpleSource,
    SourceConfig,
    SourceRegistry,
)


@SourceRegistry.register
class LinkedinPagesSource(SimpleSource[LinkedinPagesSourceConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LINKEDINPAGES

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.LINKEDINPAGES,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Linkedin Pages",
            iconPath="/static/services/linkedin_pages.png",
            fields=cast(list[FieldType], []),
            unreleasedSource=True,
        )
