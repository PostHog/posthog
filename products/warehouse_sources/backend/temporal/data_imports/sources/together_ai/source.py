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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import TogetherAISourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.together_ai.settings import (
    ENDPOINTS,
    TOGETHER_AI_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.together_ai.together_ai import (
    get_status_code,
    together_ai_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TogetherAISource(SimpleSource[TogetherAISourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TOGETHERAI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TOGETHER_AI,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Together AI",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Together AI API key to sync your fine-tuning jobs, batch inference jobs, files, dedicated endpoints, evaluations, and the model catalog into the PostHog Data warehouse.

You can find or create an API key in your [Together AI settings](https://api.together.xyz/settings/api-keys).""",
            iconPath="/static/services/together_ai.png",
            docsUrl="https://posthog.com/docs/cdp/sources/together-ai",
            keywords=["together", "ai", "llm", "inference", "fine-tuning"],
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
            unreleasedSource=True,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.together_ai.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid/revoked key surfaces as a requests HTTPError from `raise_for_status()`.
            # Match the stable status text and base host, not the per-request path.
            "401 Client Error: Unauthorized for url: https://api.together.xyz": "Your Together AI API key is invalid or has been revoked. Create a new API key in your Together AI settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.together.xyz": "Your Together AI API key does not have permission to access this data. Check the key in your Together AI settings, then reconnect.",
        }

    def get_schemas(
        self,
        config: TogetherAISourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Together's list endpoints return the whole collection in one response with no pagination
        # and no server-side timestamp filters (see settings.py), so every table is full refresh only.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
                detected_primary_keys=TOGETHER_AI_ENDPOINTS[endpoint].primary_keys,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: TogetherAISourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        try:
            status = get_status_code(config.api_key, schema_name)
        except Exception:
            return False, "Could not reach the Together AI API. Check your network connection and try again."

        if status == 200:
            return True, None
        if status == 401:
            return False, "Invalid Together AI API key. Check the key in your Together AI settings, then reconnect."
        if status == 403:
            # Accept a valid-but-restricted key at source-create so the user can still sync the
            # tables the key can reach; only fail the per-schema check.
            if schema_name is None:
                return True, None
            return False, f"Your Together AI API key does not have permission to sync '{schema_name}'."
        return False, f"Unexpected response from the Together AI API (status {status})."

    def source_for_pipeline(self, config: TogetherAISourceConfig, inputs: SourceInputs) -> SourceResponse:
        return together_ai_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
        )
