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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.peecai import PeecAISourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.peec_ai.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.peec_ai.peec_ai import (
    PeecAIResumeConfig,
    peec_ai_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.peec_ai.settings import (
    AUTH_ERRORS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class PeecAISource(ResumableSource[PeecAISourceConfig, PeecAIResumeConfig]):
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://docs.peec.ai/api/changelog"
    lists_tables_without_credentials = True

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PEECAI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.PEECAI,
            category=DataWarehouseSourceCategory.ANALYTICS,
            keywords=["peec.ai", "peecai", "ai brand visibility", "ai search analytics"],
            label="Peec AI",
            iconPath="/static/services/peec.png",
            caption=(
                "Create a key in [Peec AI API keys](https://app.peec.ai/api-keys). "
                "Use a project key, or enter a project ID with a company key. "
                "Your Peec AI plan must include API access. The start date applies to chats."
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
                        label="Project ID (required for company keys)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="or_...",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="start_date",
                        label="Start date",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="YYYY-MM-DD",
                        secret=False,
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )

    def get_schemas(
        self,
        config: PeecAISourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only={"chats"})

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "400 Client Error": AUTH_ERRORS[400],
            "401 Client Error": AUTH_ERRORS[401],
            "403 Client Error": AUTH_ERRORS[403],
            "Missing API Key": AUTH_ERRORS[401],
            "Invalid API Key": AUTH_ERRORS[401],
        }

    def validate_credentials(
        self, config: PeecAISourceConfig, team_id: int, schema_name: str | None = None, api_version: str | None = None
    ) -> tuple[bool, str | None]:
        return validate_credentials(config, self.resolve_api_version(api_version))

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PeecAIResumeConfig]:
        return ResumableSourceManager(inputs, PeecAIResumeConfig)

    def source_for_pipeline(
        self,
        config: PeecAISourceConfig,
        resumable_source_manager: ResumableSourceManager[PeecAIResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return peec_ai_source(
            config=config,
            endpoint=inputs.schema_name,
            api_version=self.resolve_api_version(inputs.api_version),
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
        )
