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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GroqSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.groq.groq import (
    groq_source,
    validate_credentials as validate_groq_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.groq.settings import GROQ_ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GroqSource(SimpleSource[GroqSourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GROQ

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GROQ,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Groq",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["llm", "ai", "inference", "batch"],
            caption="""Enter your Groq API key to pull your Groq batch jobs, files, and model catalog into the PostHog Data warehouse.

Create an API key in the [Groq console](https://console.groq.com/keys). Groq exposes no usage or spend API, so this source covers batch-job and file bookkeeping plus the model catalog.""",
            iconPath="/static/services/groq.png",
            docsUrl="https://posthog.com/docs/cdp/sources/groq",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="gsk_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.groq.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # 401/403 surface as a requests HTTPError when `_fetch_page` calls `raise_for_status()`.
            # Retrying can never fix a credential/permission problem, so fail the sync. Match the
            # stable status text and base host, not the per-request path.
            "401 Client Error: Unauthorized for url: https://api.groq.com": "Your Groq API key is invalid or has been revoked. Create a new key in the Groq console, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.groq.com": "Your Groq API key is missing the permissions needed to sync this data. Check the key in the Groq console, then reconnect.",
        }

    def get_schemas(
        self,
        config: GroqSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Groq exposes no server-side timestamp filter on any list endpoint, so every table is full
        # refresh only.
        schemas = [
            SourceSchema(
                name=endpoint.name,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
                detected_primary_keys=endpoint.primary_keys,
                should_sync_default=endpoint.should_sync_default,
                description=endpoint.description,
            )
            for endpoint in GROQ_ENDPOINTS.values()
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: GroqSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        ok, status_code = validate_groq_credentials(config.api_key)
        if ok:
            return True, None
        if status_code == 401:
            return False, "Invalid Groq API key"
        if status_code == 403:
            return False, "Your Groq API key is missing the permissions needed to sync this data"
        return False, "Could not connect to Groq with the provided API key"

    def source_for_pipeline(self, config: GroqSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return groq_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
        )
