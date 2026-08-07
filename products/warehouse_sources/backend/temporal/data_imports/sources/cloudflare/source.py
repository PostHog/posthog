from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.cloudflare.cloudflare import (
    cloudflare_source,
    validate_credentials as validate_cloudflare_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudflare.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cloudflare import (
    CloudflareSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CloudflareSource(SimpleSource[CloudflareSourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    supported_versions = ("v4",)
    default_version = "v4"
    api_docs_url = "https://developers.cloudflare.com/api/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CLOUDFLARE

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.cloudflare.com": "Cloudflare authentication failed. Please check your API token.",
            "403 Client Error: Forbidden for url: https://api.cloudflare.com": "Cloudflare denied access. Please check that your API token has read permissions for this resource.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CLOUDFLARE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Cloudflare",
            caption="""Enter your Cloudflare API token to pull your Cloudflare configuration, security, and usage data into the PostHog Data warehouse.

Create an API token in the [Cloudflare dashboard](https://dash.cloudflare.com/profile/api-tokens) with read permissions for the areas you want to sync, such as Account Settings, Zone, DNS, Firewall Services, Logs, Workers, and Access. Zone tables are synced from every zone the token can read, and account tables from every account. Zones and accounts the token can't read are skipped.""",
            iconPath="/static/services/cloudflare.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/cloudflare",
            releaseStatus=ReleaseStatus.BETA,
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
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Most v4 REST lists are small configuration tables with no updated-since
        # filter, so they full refresh. Only endpoints in INCREMENTAL_FIELDS take a
        # server-side timestamp filter.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=endpoint in INCREMENTAL_FIELDS,
                supports_append=endpoint in INCREMENTAL_FIELDS,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self,
        config: CloudflareSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        is_valid, status = validate_cloudflare_credentials(config.api_token)
        if is_valid:
            return True, None

        if status is None or status == 429 or status >= 500:
            return (
                False,
                "Couldn't reach Cloudflare to verify your API token. Please try again in a moment.",
            )
        return (
            False,
            "Invalid Cloudflare API token. Please check the token has read permissions and hasn't been revoked.",
        )

    def source_for_pipeline(self, config: CloudflareSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return cloudflare_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
