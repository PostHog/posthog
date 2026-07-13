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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GoldcastSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.goldcast.goldcast import (
    goldcast_source,
    validate_credentials as validate_goldcast_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.goldcast.settings import (
    ENDPOINTS,
    GOLDCAST_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class GoldcastSource(SimpleSource[GoldcastSourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GOLDCAST

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GOLDCAST,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Goldcast",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your Goldcast API token to sync your virtual event and webinar data into the PostHog Data warehouse.

An org admin can create a personal access token in Goldcast Studio under **Settings → Tokens**. The token is shown only once, so copy it immediately.

API access requires a Pro, Premium, or Enterprise plan, and the token feature must be enabled by Goldcast support.""",
            iconPath="/static/services/goldcast.png",
            docsUrl="https://posthog.com/docs/cdp/sources/goldcast",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="access_key",
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.goldcast.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked token surfaces as a requests HTTPError when `_fetch` calls
            # `raise_for_status()`. Retrying can never satisfy a credential problem, so stop the
            # sync. Match the stable status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://customapi.goldcast.io": "Your Goldcast API token is invalid or has been revoked. Create a new token in Goldcast Studio under Settings → Tokens, then reconnect.",
            "403 Client Error: Forbidden for url: https://customapi.goldcast.io": "Your Goldcast API token does not have API access. Confirm your plan supports the API and that Goldcast support has enabled the token feature, then reconnect.",
        }

    def get_schemas(
        self,
        config: GoldcastSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Goldcast exposes no server-side timestamp filter, so every endpoint is full refresh only
        # — incremental would re-fetch every record each sync anyway.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
                detected_primary_keys=GOLDCAST_ENDPOINTS[endpoint].primary_keys,
                should_sync_default=GOLDCAST_ENDPOINTS[endpoint].should_sync_default,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: GoldcastSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_goldcast_credentials(config.access_key):
            return True, None

        return False, "Invalid Goldcast API token"

    def source_for_pipeline(self, config: GoldcastSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return goldcast_source(
            access_key=config.access_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
        )
