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
from products.warehouse_sources.backend.temporal.data_imports.sources.cohere.cohere import (
    cohere_source,
    validate_credentials as validate_cohere_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cohere.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CohereSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CohereSource(SimpleSource[CohereSourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://docs.cohere.com/reference/about"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.COHERE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.COHERE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Cohere",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Cohere API key to pull your Cohere assets and job history into the PostHog Data warehouse.

Create an API key in your [Cohere dashboard](https://dashboard.cohere.com/api-keys). Prefer a production key: trial keys are capped at 1,000 API calls per month, which a recurring sync can exhaust.
""",
            iconPath="/static/services/cohere.png",
            docsUrl="https://posthog.com/docs/cdp/sources/cohere",
            keywords=["llm", "ai", "embeddings", "fine-tuning"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.cohere.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked key surfaces as a requests HTTPError when `_fetch_page` calls
            # `raise_for_status()`. Retrying can't fix a credential problem, so stop the sync. Match
            # the stable status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.cohere.com": "Your Cohere API key is invalid or has been revoked. Create a new key in your Cohere dashboard, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.cohere.com": "Your Cohere API key is missing the permissions needed to sync this data. Check the key permissions in your Cohere dashboard, then reconnect.",
        }

    def get_schemas(
        self,
        config: CohereSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Cohere exposes no reliable server-side timestamp range filter across these list endpoints
        # (only /datasets documents before/after created-at filters, and the entities are mutable
        # with tiny row counts), so every endpoint is full refresh only. Statuses and timestamps
        # mutate in place, so append-only would drop those updates.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: CohereSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_cohere_credentials(config.api_key):
            return True, None

        return False, "Invalid Cohere API key"

    def source_for_pipeline(self, config: CohereSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return cohere_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
        )
