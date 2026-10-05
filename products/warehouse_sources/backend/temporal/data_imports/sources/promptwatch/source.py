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
    schema_for_resource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.promptwatch import (
    PromptWatchSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.promptwatch.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.promptwatch.promptwatch import (
    PromptWatchResumeConfig,
    promptwatch_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.promptwatch.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    NON_RETRYABLE_ERRORS,
    PAGINATED_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PromptWatchSource(ResumableSource[PromptWatchSourceConfig, PromptWatchResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://promptwatch.com/docs/v2/openapi.json"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PROMPTWATCH

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return dict(NON_RETRYABLE_ERRORS)

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: PromptWatchSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only={"responses"})

    def validate_credentials(
        self,
        config: PromptWatchSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config, self.resolve_api_version(api_version))

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PromptWatchResumeConfig]:
        return ResumableSourceManager(inputs, PromptWatchResumeConfig)

    def source_for_pipeline(
        self,
        config: PromptWatchSourceConfig,
        resumable_source_manager: ResumableSourceManager[PromptWatchResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        schema_for_resource(CANONICAL_DESCRIPTIONS, inputs.schema_name)
        return SourceResponse(
            name=inputs.schema_name,
            items=lambda: promptwatch_source(
                config, inputs, resumable_source_manager, self.resolve_api_version(inputs.api_version)
            ),
            primary_keys=["id"],
            sort_mode="asc" if inputs.schema_name in PAGINATED_ENDPOINTS else None,
            supports_resume=inputs.schema_name in PAGINATED_ENDPOINTS,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.PROMPTWATCH,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Promptwatch",
            iconPath="/static/services/promptwatch.png",
            releaseStatus=ReleaseStatus.ALPHA,
            caption=(
                "Create a read-only API key in Promptwatch under Settings > API Keys. "
                "Requires the Explore plan or higher. Syncs use your account's API units (hourly request quota). "
                "Each paginated table allows up to 1,000 rows per sync. Responses start from your chosen date."
            ),
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="project_id",
                        secret=False,
                        label="Project ID (required for organization API keys)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="00000000-0000-0000-0000-000000000000",
                    ),
                    SourceFieldInputConfig(
                        name="start_date",
                        secret=False,
                        label="Response start date",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="YYYY-MM-DD",
                    ),
                ],
            ),
        )
