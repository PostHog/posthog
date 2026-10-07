from typing import cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.givebutter import (
    GivebutterSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.givebutter.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.givebutter.givebutter import (
    AUTH_ERROR,
    PERMISSION_ERROR,
    GivebutterResumeConfig,
    givebutter_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.givebutter.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GivebutterSource(ResumableSource[GivebutterSourceConfig, GivebutterResumeConfig]):
    lists_tables_without_credentials = True
    api_docs_url = "https://docs.givebutter.com/api-reference/authentication"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GIVEBUTTER

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error:": AUTH_ERROR,
            "403 Client Error:": PERMISSION_ERROR,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: GivebutterSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: GivebutterSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config.api_key, schema_name)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[GivebutterResumeConfig]:
        return ResumableSourceManager(inputs, GivebutterResumeConfig)

    def source_for_pipeline(
        self,
        config: GivebutterSourceConfig,
        resumable_source_manager: ResumableSourceManager[GivebutterResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return givebutter_source(config.api_key, inputs, resumable_source_manager)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.GIVEBUTTER,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Givebutter",
            caption="Enter an API key from Settings > Integrations > API Keys in your Givebutter dashboard.",
            docsUrl="https://posthog.com/docs/cdp/sources/givebutter",
            iconPath="/static/services/givebutter.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        secret=True,
                        placeholder="",
                    )
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )
