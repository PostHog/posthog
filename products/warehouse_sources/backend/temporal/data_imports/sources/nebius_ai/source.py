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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import NebiusAISourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.nebius_ai.nebius_ai import (
    NebiusAIResumeConfig,
    nebius_ai_source,
    validate_credentials as validate_nebius_ai_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.nebius_ai.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    NEBIUS_AI_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class NebiusAISource(ResumableSource[NebiusAISourceConfig, NebiusAIResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NEBIUSAI

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.NEBIUS_AI,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Nebius AI",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Nebius AI Studio (Token Factory) API key to pull your Nebius inference platform metadata into the PostHog Data warehouse.

You can create an API key in the [Nebius AI Studio console](https://studio.nebius.com/settings/api-keys). A key with read access is enough to sync models, files, batches, and fine-tuning jobs.""",
            iconPath="/static/services/nebius_ai.png",
            docsUrl="https://posthog.com/docs/cdp/sources/nebius-ai",
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.nebius_ai.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or expired key surfaces as a requests HTTPError when `_fetch_page` calls
            # `raise_for_status()`. Retrying can never satisfy a credential problem, so stop the sync.
            # Match the stable status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.tokenfactory.nebius.com": "Your Nebius AI API key is invalid or has expired. Create a new key in the Nebius AI Studio console, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.tokenfactory.nebius.com": "Your Nebius AI API key does not have the permissions needed to sync this data. Grant read access to the key, then reconnect.",
        }

    def get_schemas(
        self,
        config: NebiusAISourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = NEBIUS_AI_ENDPOINTS[endpoint]
            # Every stream is full-refresh: the API exposes no server-side timestamp filter, so
            # incremental would page the whole list every run at no cost saving.
            return SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: NebiusAISourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # Forward the transport result verbatim so transient failures and permission errors keep
        # their distinct messages instead of collapsing into a misleading "invalid key".
        return validate_nebius_ai_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[NebiusAIResumeConfig]:
        # Namespace resume state by schema so sibling endpoints in the same job never share a cursor.
        return ResumableSourceManager[NebiusAIResumeConfig](inputs, NebiusAIResumeConfig).with_namespace(
            inputs.schema_name
        )

    def source_for_pipeline(
        self,
        config: NebiusAISourceConfig,
        resumable_source_manager: ResumableSourceManager[NebiusAIResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return nebius_ai_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
