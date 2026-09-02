from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.clever.clever import (
    CleverResumeConfig,
    clever_source,
    validate_credentials as validate_clever_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clever.settings import (
    CLEVER_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.clever import CleverSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CleverSource(ResumableSource[CleverSourceConfig, CleverResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v3.0",)
    default_version = "v3.0"
    api_docs_url = "https://dev.clever.com/docs/new-in-api-v3"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CLEVER

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.clever.com": "Clever authentication failed. Check the district bearer token and try again.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.clever.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CLEVER,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Clever",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["rostering", "k-12", "education", "sis"],
            caption="""Enter the bearer token Clever issued to your app for a district. Find it in your Clever
app dashboard, under that district's **Data Sources** tab in the **API Token** section. See the
[Clever API overview](https://dev.clever.com/docs/api-overview) for details.

Each token is scoped to a single district — connect a separate source per district you want to sync.
Rostering data beyond districts requires the district's Clever Secure Sync (Clever Complete) subscription.""",
            iconPath="/static/services/clever.png",
            docsUrl="https://posthog.com/docs/cdp/sources/clever",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="bearer_token",
                        label="District bearer token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_schemas(
        self,
        config: CleverSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: CleverSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_clever_credentials(config.bearer_token)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CleverResumeConfig]:
        return ResumableSourceManager[CleverResumeConfig](inputs, CleverResumeConfig)

    def source_for_pipeline(
        self,
        config: CleverSourceConfig,
        resumable_source_manager: ResumableSourceManager[CleverResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        endpoint_config = CLEVER_ENDPOINTS[inputs.schema_name]
        resource = clever_source(
            bearer_token=config.bearer_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
        return SourceResponse(
            name=resource.name,
            items=lambda: resource,
            primary_keys=["id"],
            column_hints=resource.column_hints,
            partition_mode="datetime" if endpoint_config.partition_key else None,
            partition_format="month" if endpoint_config.partition_key else None,
            partition_keys=[endpoint_config.partition_key] if endpoint_config.partition_key else None,
            sort_mode="asc",
        )
