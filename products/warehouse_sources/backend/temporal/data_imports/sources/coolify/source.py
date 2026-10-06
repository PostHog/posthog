from typing import Optional, cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.coolify.coolify import (
    coolify_source,
    validate_credentials as validate_coolify_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.coolify.settings import (
    COOLIFY_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.coolify import (
    CoolifySourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CoolifySource(SimpleSource[CoolifySourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # Coolify's API has a single, never-versioned base (`/api/v1` on every instance) and no
    # version header or changelog of version tokens, so it stays on the unversioned default.
    api_docs_url = "https://coolify.io/docs/api-reference/authorization"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.COOLIFY

    @property
    def connection_host_fields(self) -> list[str]:
        # `base_url` is where the stored API token is sent, so retargeting it must re-require the token.
        return ["base_url"]

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.coolify.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # The base host is customer-specific (self-hosted instances), so the keys match the
            # stable status text rather than a fixed host. Coolify answers an unrecognized token
            # with 400 "Invalid token." rather than 401, so both map to the credential message.
            "400 Client Error: Bad Request for url": "Coolify rejected the API token. Check the token, or create a new one under Keys & Tokens > API tokens on your Coolify instance, then reconnect.",
            "401 Client Error: Unauthorized for url": "Coolify rejected the API token. Check the token, or create a new one under Keys & Tokens > API tokens on your Coolify instance, then reconnect.",
            "403 Client Error: Forbidden for url": "Your API token doesn't have read permission. Create a token with read permission under Keys & Tokens > API tokens on your Coolify instance, then reconnect.",
        }

    def get_schemas(
        self,
        config: CoolifySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: CoolifySourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_coolify_credentials(config.base_url, config.api_token, team_id=team_id, schema_name=schema_name)

    def source_for_pipeline(self, config: CoolifySourceConfig, inputs: SourceInputs) -> SourceResponse:
        endpoint_config = COOLIFY_ENDPOINTS[inputs.schema_name]
        resource = coolify_source(
            base_url=config.base_url,
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
        )
        response = SourceResponse(
            name=resource.name,
            items=lambda: resource,
            primary_keys=endpoint_config.primary_keys,
            column_hints=resource.column_hints,
        )

        if endpoint_config.partition_key:
            response.partition_count = 1
            response.partition_size = 1
            response.partition_mode = "datetime"
            response.partition_format = "month"
            response.partition_keys = [endpoint_config.partition_key]

        return response

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.COOLIFY,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Coolify",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Coolify instance URL and an API token to pull your servers, projects, applications, databases, services, deployments, and teams into the PostHog Data warehouse.

Create a token under **Keys & Tokens > API tokens** in your Coolify dashboard. A read-only token is enough, because this source never writes or deploys.

The instance URL is where your Coolify dashboard runs, for example `https://coolify.example.com` (use `https://app.coolify.io` for Coolify Cloud).""",
            iconPath="/static/services/coolify.png",
            docsUrl="https://posthog.com/docs/cdp/sources/coolify",
            keywords=["paas", "self-hosted", "coollabs", "deployments"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="base_url",
                        label="Instance URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://coolify.example.com",
                        secret=False,
                    ),
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
