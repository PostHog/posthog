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
from products.warehouse_sources.backend.temporal.data_imports.sources.bland_ai.bland_ai import (
    BASE_URL,
    BlandAIResumeConfig,
    bland_ai_source,
    validate_credentials as validate_bland_ai_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bland_ai.settings import BLAND_AI_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import BlandAISourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BlandAISource(ResumableSource[BlandAISourceConfig, BlandAIResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BLANDAI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BLAND_AI,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Bland AI",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption=(
                "Enter your Bland AI API key to sync your AI phone calls, transcripts, and "
                "conversational pathways into the PostHog Data warehouse. Find your key in the "
                "[Bland dashboard](https://app.bland.ai/) under **Settings → API keys**."
            ),
            iconPath="/static/services/bland_ai.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/bland-ai",
            keywords=["ai", "phone calls", "voice agent", "transcripts"],
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

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.bland_ai.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # Bland returns 401 AUTH_FAILURE for a missing/invalid key on every endpoint. There's no
        # scope/permission model, so a 401 is always a credential problem retrying can't fix.
        return {
            f"401 Client Error: Unauthorized for url: {BASE_URL}": (
                "Your Bland AI API key is invalid or has been revoked. Create a new key in the "
                "Bland dashboard, then reconnect."
            ),
        }

    def get_schemas(
        self,
        config: BlandAISourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint_config.name,
                supports_incremental=endpoint_config.supports_incremental,
                supports_append=endpoint_config.supports_incremental,
                incremental_fields=endpoint_config.incremental_fields,
                should_sync_default=endpoint_config.should_sync_default,
                description=endpoint_config.description,
            )
            for endpoint_config in BLAND_AI_ENDPOINTS.values()
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: BlandAISourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_bland_ai_credentials(config.api_key):
            return True, None

        return False, "Invalid Bland AI API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[BlandAIResumeConfig]:
        return ResumableSourceManager[BlandAIResumeConfig](inputs, BlandAIResumeConfig)

    def source_for_pipeline(
        self,
        config: BlandAISourceConfig,
        resumable_source_manager: ResumableSourceManager[BlandAIResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return bland_ai_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
