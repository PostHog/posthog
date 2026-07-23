from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cast_ai.cast_ai import (
    CastAiResumeConfig,
    cast_ai_source,
    validate_credentials as validate_castai_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cast_ai.settings import (
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.castai import CastAiSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CastAiSource(ResumableSource[CastAiSourceConfig, CastAiResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://docs.cast.ai/docs/api-access"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CASTAI

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "CAST AI authentication failed. Please check your API key.",
            "403 Client Error": "CAST AI API key does not have the required permissions.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.cast_ai.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: CastAiSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: CastAiSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_castai_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CastAiResumeConfig]:
        return ResumableSourceManager[CastAiResumeConfig](inputs, CastAiResumeConfig)

    def source_for_pipeline(
        self,
        config: CastAiSourceConfig,
        resumable_source_manager: ResumableSourceManager[CastAiResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return cast_ai_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CAST_AI,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="CAST AI",
            caption="Import Kubernetes cost and savings reports from your CAST AI organization.",
            docsUrl="https://posthog.com/docs/cdp/sources/cast-ai",
            iconPath="/static/services/cast_ai.png",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["kubernetes", "finops", "k8s"],
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
                ],
            ),
        )
