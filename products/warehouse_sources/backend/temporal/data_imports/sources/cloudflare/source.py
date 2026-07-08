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
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudflare.cloudflare import (
    cloudflare_source,
    validate_credentials as validate_cloudflare_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudflare.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CloudflareSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CloudflareSource(SimpleSource[CloudflareSourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CLOUDFLARE

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.cloudflare.com": "Cloudflare authentication failed. Please check your API token.",
            "403 Client Error: Forbidden for url: https://api.cloudflare.com": "Cloudflare denied access. Please check that your API token has read permissions for this resource.",
        }

    def get_retryable_errors(self) -> set[str]:
        # A 429 (rate limit) or 5xx is retried internally up to MAX_RETRY_ATTEMPTS honoring
        # Retry-After; if it still exhausts, it's transient and self-recovering, so let
        # Temporal retry the activity without surfacing it as tracked exception noise.
        return {"Cloudflare API error (retryable)"}

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CLOUDFLARE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Cloudflare",
            caption="""Enter your Cloudflare API token to pull your Cloudflare configuration data into the PostHog Data warehouse.

Create an API token in the [Cloudflare dashboard](https://dash.cloudflare.com/profile/api-tokens) with read permissions for Account Settings, Zone, and DNS. DNS records are synced from every zone the token can access.""",
            iconPath="/static/services/cloudflare.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/cloudflare",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.cloudflare.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: CloudflareSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # v4 REST lists are small configuration tables with no updated-since
        # filters; the analytics datasets live in the GraphQL API (follow-up).
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
        self, config: CloudflareSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_cloudflare_credentials(config.api_token):
            return True, None

        return False, "Invalid Cloudflare API token"

    def source_for_pipeline(self, config: CloudflareSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return cloudflare_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
        )
