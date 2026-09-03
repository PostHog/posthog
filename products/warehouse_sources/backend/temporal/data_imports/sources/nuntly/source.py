from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.errors import auth_non_retryable_errors
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.nuntly import NuntlySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.nuntly.nuntly import (
    NUNTLY_BASE_URL,
    NuntlyResumeConfig,
    nuntly_source,
    validate_credentials as validate_nuntly_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.nuntly.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class NuntlySource(ResumableSource[NuntlySourceConfig, NuntlyResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://nuntly.com/docs/api-reference/introduction"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NUNTLY

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return auth_non_retryable_errors(NUNTLY_BASE_URL, service="Nuntly")

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.nuntly.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: NuntlySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: NuntlySourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        is_valid, _ = validate_nuntly_credentials(config.api_key)
        if is_valid:
            return True, None
        return False, "Invalid credentials"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[NuntlyResumeConfig]:
        return ResumableSourceManager[NuntlyResumeConfig](inputs, NuntlyResumeConfig)

    def source_for_pipeline(
        self,
        config: NuntlySourceConfig,
        resumable_source_manager: ResumableSourceManager[NuntlyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return nuntly_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.NUNTLY,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            releaseStatus=ReleaseStatus.ALPHA,
            label="Nuntly",
            caption="Enter your Nuntly API key. You can create one in the "
            "[Nuntly dashboard](https://nuntly.com/docs/guides/api-keys).",
            docsUrl="https://posthog.com/docs/cdp/sources/nuntly",
            iconPath="/static/services/nuntly.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="apk_...",
                        secret=True,
                    ),
                ],
            ),
        )
