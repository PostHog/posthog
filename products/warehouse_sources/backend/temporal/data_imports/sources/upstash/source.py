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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import UpstashSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.upstash.settings import (
    ENDPOINTS,
    UPSTASH_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.upstash.upstash import (
    upstash_source,
    validate_credentials as validate_upstash_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class UpstashSource(SimpleSource[UpstashSourceConfig]):
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://upstash.com/docs/devops/developer-api/introduction"
    # get_schemas iterates a static endpoint catalog with no I/O, so the public docs can render the
    # Supported tables section without credentials.
    lists_tables_without_credentials = True

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.UPSTASH

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.UPSTASH,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Upstash",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Upstash account email and a management API key to pull your Upstash Redis databases, usage stats, teams, and vector indexes into the PostHog Data warehouse.

Create a management API key in the [Upstash console](https://console.upstash.com/account/api) under **Account > Management API**. The Developer API is only available to native Upstash accounts (not Vercel or Fly.io marketplace accounts).""",
            iconPath="/static/services/upstash.png",
            docsUrl="https://posthog.com/docs/cdp/sources/upstash",
            keywords=["redis", "serverless", "qstash", "vector"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="email",
                        label="Account email",
                        type=SourceFieldInputConfigType.EMAIL,
                        required=True,
                        placeholder="you@example.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Management API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.upstash.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # 401/403 surface as a requests HTTPError when `_fetch` calls raise_for_status(). Retrying
            # never satisfies a credential problem, so stop the sync. Match the stable status text and
            # base host, not the per-request path.
            "401 Client Error: Unauthorized for url: https://api.upstash.com": "Your Upstash email or management API key is invalid or has been revoked. Create a new key in the Upstash console, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.upstash.com": "Your Upstash management API key is not authorized for this resource. Check the key, then reconnect.",
        }

    def get_schemas(
        self,
        config: UpstashSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Every Upstash management endpoint is full refresh (no pagination, no server-side time
        # filter), so no schema advertises incremental fields.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
                should_sync_default=UPSTASH_ENDPOINTS[endpoint].should_sync_default,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: UpstashSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_upstash_credentials(config.email, config.api_key)

    def source_for_pipeline(self, config: UpstashSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return upstash_source(
            email=config.email,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
        )
