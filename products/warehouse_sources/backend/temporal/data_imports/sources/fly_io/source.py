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
from products.warehouse_sources.backend.temporal.data_imports.sources.fly_io.fly_io import (
    fly_io_source,
    validate_credentials as validate_fly_io_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.fly_io.settings import FLY_IO_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import FlyIoSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class FlyIoSource(SimpleSource[FlyIoSourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FLYIO

    @property
    def connection_host_fields(self) -> list[str]:
        # The stored token is scoped to an org, but the slug decides which org's apps/machines/volumes
        # get synced. Changing it must re-require the token so an editor can't retarget the preserved
        # token at another org it happens to reach.
        return ["organization_slug"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.FLY_IO,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Fly.io",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Sync your Fly.io apps, machines, and volumes into the PostHog Data warehouse.

Create an organization-scoped token with `fly tokens create org` (or from the **Tokens** section of your Fly.io dashboard) and paste it below. A read-only org token is sufficient.""",
            iconPath="/static/services/fly_io.png",
            docsUrl="https://posthog.com/docs/cdp/sources/fly-io",
            keywords=["fly", "machines", "infrastructure", "cloud"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="FlyV1 ...",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="organization_slug",
                        label="Organization slug",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="personal",
                        caption="Your Fly.io organization slug — use `personal` for your personal org. Find it with `fly orgs list`.",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.fly_io.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid, revoked, or expired token surfaces as an HTTPError when `_fetch_page`
            # calls `raise_for_status()`. Retrying can never satisfy a credential problem, so stop
            # the sync. Match the stable status text and base host, not the per-request path.
            "401 Client Error: Unauthorized for url: https://api.machines.dev": "Your Fly.io API token is invalid or expired. Create a new token with `fly tokens create org` and reconnect.",
            "403 Client Error: Forbidden for url: https://api.machines.dev": "Your Fly.io API token does not have access to this organization or resource. Check the token's scope and reconnect.",
        }

    def get_schemas(
        self,
        config: FlyIoSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=name,
                # Fly.io has no verified server-side time filter for any stream, so full refresh only.
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
                detected_primary_keys=endpoint_config.primary_keys,
            )
            for name, endpoint_config in FLY_IO_ENDPOINTS.items()
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: FlyIoSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_fly_io_credentials(config.api_token, config.organization_slug)

    def source_for_pipeline(self, config: FlyIoSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return fly_io_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            org_slug=config.organization_slug,
            logger=inputs.logger,
        )
