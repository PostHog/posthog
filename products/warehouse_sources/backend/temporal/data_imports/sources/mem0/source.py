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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import Mem0SourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mem0.mem0 import (
    Mem0ResumeConfig,
    mem0_source,
    validate_credentials as validate_mem0_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mem0.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    MEM0_ENDPOINTS,
    MEMORIES_ENDPOINT,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

# Mem0 can push memory:add/update/delete/categorize webhooks, but we deliberately don't wire a
# WebhookSource here: deliveries carry only {event_details: {id, data.memory, event}} — no
# categories, metadata, timestamps, or owning entity ids — and Mem0 documents no signing
# secret/verification mechanism. Once a schema enters webhook sync mode the webhook feed
# replaces the poll, which would permanently degrade the memories table to text-only rows.
# The server-side `updated_at`/`created_at` filters on POST /v3/memories/ already make
# scheduled incremental pulls cheap, and GET /v1/events/ covers the operation-event stream
# with full fidelity.


@SourceRegistry.register
class Mem0Source(ResumableSource[Mem0SourceConfig, Mem0ResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MEM0

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MEM0,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Mem0",
            caption="""Enter your Mem0 API key to automatically pull your Mem0 memories, entities, and operation events into the PostHog Data warehouse.

You can find your API key in the [Mem0 dashboard](https://app.mem0.ai/dashboard/api-keys).""",
            iconPath="/static/services/mem0.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/mem0",
            keywords=["memory", "ai", "agents", "llm"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="m0-...",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="org_id",
                        label="Organization ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="org_...",
                        caption="Optional. Scopes the entities table to a specific Mem0 organization.",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="project_id",
                        label="Project ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="proj_...",
                        caption="Optional. Scopes the entities table to a specific Mem0 project.",
                        secret=False,
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.mem0.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # Invalid/revoked keys surface as a requests HTTPError from `_fetch_json`'s
            # `raise_for_status()`. Match the stable status text and base host, not the
            # per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.mem0.ai": "Your Mem0 API key is invalid or has been revoked. Create a new API key in the Mem0 dashboard, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.mem0.ai": "Your Mem0 API key does not have access to this data. Check the key's project access in the Mem0 dashboard, then reconnect.",
        }

    def get_schemas(
        self,
        config: Mem0SourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            has_incremental = bool(INCREMENTAL_FIELDS.get(endpoint))
            return SourceSchema(
                name=endpoint,
                # Incremental pulls re-fetch updated rows, so only merge (not append) keeps the
                # table duplicate-free.
                supports_incremental=has_incremental,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=MEM0_ENDPOINTS[endpoint].should_sync_default,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: Mem0SourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_mem0_credentials(config.api_key):
            return True, None

        return False, "Invalid Mem0 API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[Mem0ResumeConfig]:
        return ResumableSourceManager[Mem0ResumeConfig](inputs, Mem0ResumeConfig)

    def source_for_pipeline(
        self,
        config: Mem0SourceConfig,
        resumable_source_manager: ResumableSourceManager[Mem0ResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return mem0_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field
            and inputs.schema_name == MEMORIES_ENDPOINT,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
            org_id=config.org_id,
            project_id=config.project_id,
        )
