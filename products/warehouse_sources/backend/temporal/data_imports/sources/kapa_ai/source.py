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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.kapaai import KapaAISourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.kapa_ai.kapa_ai import (
    AUTH_ERRORS,
    KapaResumeConfig,
    kapa_ai_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.kapa_ai.settings import ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class KapaAISource(ResumableSource[KapaAISourceConfig, KapaResumeConfig]):
    lists_tables_without_credentials = True
    api_docs_url = "https://docs.kapa.ai/api/reference"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.KAPAAI

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {f"{status} Client Error": message for status, message in AUTH_ERRORS.items()}

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.kapa_ai.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: KapaAISourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(
            ENDPOINTS, {name: endpoint.incremental_fields for name, endpoint in ENDPOINTS.items()}, names
        )

    def validate_credentials(
        self,
        config: KapaAISourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config.api_key, config.project_id, team_id, schema_name)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[KapaResumeConfig]:
        return ResumableSourceManager(inputs, KapaResumeConfig)

    def source_for_pipeline(
        self,
        config: KapaAISourceConfig,
        resumable_source_manager: ResumableSourceManager[KapaResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return kapa_ai_source(
            api_key=config.api_key,
            project_id=config.project_id,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.KAPAAI,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="kapa.ai",
            docsUrl="https://posthog.com/docs/cdp/sources/kapa-ai",
            iconPath="/static/services/kapa_ai.png",
            keywords=["ai assistant", "docs", "support", "conversations"],
            caption="Create an API key in kapa.ai under Configuration > API Keys. Find your project ID under Settings > Projects.",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        placeholder="",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="project_id",
                        label="Project ID",
                        placeholder="",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        secret=False,
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )
