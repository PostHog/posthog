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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ScaleAISourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.scale_ai.scale_ai import (
    ScaleAIResumeConfig,
    scale_ai_source,
    validate_credentials as validate_scale_ai_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.scale_ai.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    SCALE_AI_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ScaleAISource(ResumableSource[ScaleAISourceConfig, ScaleAIResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SCALEAI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SCALE_AI,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Scale AI",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Scale AI API key to sync your Scale data labeling data into the PostHog Data warehouse.

You can find your API key in the [Scale dashboard](https://dashboard.scale.com/) under **Settings → API Keys**. Use a **live-mode** key — test-mode keys have fully isolated data. Only account Managers and Admins can access API keys.
""",
            iconPath="/static/services/scale_ai.png",
            docsUrl="https://posthog.com/docs/cdp/sources/scale-ai",
            keywords=["labeling", "annotation", "rlhf", "training data"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="live_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.scale_ai.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # 401/403 surface as a requests HTTPError from raise_for_status(). Retrying can never fix a
            # credential problem, so stop the sync. Match the stable status text and base host, not the
            # per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.scale.com": "Your Scale AI API key is invalid or has been revoked. Create a new live-mode key in the Scale dashboard, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.scale.com": "Your Scale AI API key does not have permission to read this data. Check the key's permissions in the Scale dashboard, then reconnect.",
        }

    def get_schemas(
        self,
        config: ScaleAISourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _description(endpoint: str) -> str | None:
            if endpoint == "batches":
                return (
                    "Incremental sync filters on created_at, so it catches newly created batches but "
                    "not status changes to existing ones; use a full refresh to re-read batch status."
                )
            return None

        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = SCALE_AI_ENDPOINTS[endpoint]
            has_incremental = len(INCREMENTAL_FIELDS.get(endpoint, [])) > 0
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental,
                supports_append=has_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                detected_primary_keys=endpoint_config.primary_keys,
                should_sync_default=endpoint_config.should_sync_default,
                description=_description(endpoint),
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: ScaleAISourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_scale_ai_credentials(config.api_key):
            return True, None

        return False, "Invalid Scale AI API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ScaleAIResumeConfig]:
        return ResumableSourceManager[ScaleAIResumeConfig](inputs, ScaleAIResumeConfig)

    def source_for_pipeline(
        self,
        config: ScaleAISourceConfig,
        resumable_source_manager: ResumableSourceManager[ScaleAIResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return scale_ai_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
