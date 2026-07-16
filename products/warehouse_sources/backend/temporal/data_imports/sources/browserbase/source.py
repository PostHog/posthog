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
from products.warehouse_sources.backend.temporal.data_imports.sources.browserbase.browserbase import (
    browserbase_source,
    validate_credentials as validate_browserbase_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.browserbase.settings import (
    BROWSERBASE_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import BrowserbaseSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BrowserbaseSource(SimpleSource[BrowserbaseSourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BROWSERBASE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BROWSERBASE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Browserbase",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Browserbase API key to sync your Browserbase sessions and projects into the PostHog Data warehouse.

You can find your project API key in your [Browserbase dashboard](https://www.browserbase.com/settings). API keys are scoped to a single project.""",
            iconPath="/static/services/browserbase.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/browserbase",
            keywords=["browser", "automation", "agents", "sessions"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="bb_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.browserbase.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked key surfaces as an HTTPError from `raise_for_status()`. Retrying
            # can never satisfy a credential problem, so stop the sync. Match the stable status text
            # and base host, not the per-request path.
            "401 Client Error: Unauthorized for url: https://api.browserbase.com": "Your Browserbase API key is invalid or has been revoked. Create a new key in your Browserbase project settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.browserbase.com": "Your Browserbase API key does not have access to this data. Check the key's project scope, then reconnect.",
        }

    def get_schemas(
        self,
        config: BrowserbaseSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every Browserbase list endpoint is full refresh: there is no server-side timestamp filter,
        # so nothing can be synced incrementally (see settings.py).
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=BROWSERBASE_ENDPOINTS[endpoint].should_sync_default,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: BrowserbaseSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_browserbase_credentials(config.api_key):
            return True, None

        return False, "Invalid Browserbase API key"

    def source_for_pipeline(self, config: BrowserbaseSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return browserbase_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
        )
