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
from products.warehouse_sources.backend.temporal.data_imports.sources.buzzsprout.buzzsprout import (
    buzzsprout_source,
    validate_credentials as validate_buzzsprout_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.buzzsprout.settings import (
    BUZZSPROUT_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import BuzzsproutSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BuzzsproutSource(SimpleSource[BuzzsproutSourceConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BUZZSPROUT

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BUZZSPROUT,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Buzzsprout",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your Buzzsprout API token and podcast ID to sync your podcast data into the PostHog Data warehouse.

You can find both your API token and podcast ID in your [Buzzsprout API settings](https://www.buzzsprout.com/my/profile/api).""",
            iconPath="/static/services/buzzsprout.png",
            docsUrl="https://posthog.com/docs/cdp/sources/buzzsprout",
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
                    SourceFieldInputConfig(
                        name="podcast_id",
                        label="Podcast ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="123456",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.buzzsprout.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked token surfaces as a requests HTTPError when `_fetch` calls
            # `raise_for_status()`. Retrying can never satisfy a credential problem. Match the stable
            # status text and base host, not the per-request path.
            "401 Client Error: Unauthorized for url: https://www.buzzsprout.com": "Your Buzzsprout API token is invalid or has been revoked. Create a new token in your Buzzsprout account settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://www.buzzsprout.com": "Your Buzzsprout API token does not have access to this podcast. Check the token and podcast ID, then reconnect.",
        }

    def get_schemas(
        self,
        config: BuzzsproutSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                # Buzzsprout returns the full array on every request with no server-side timestamp
                # filter, so an "incremental" sync would cost the same as a full refresh. Ship full
                # refresh only — merge on the primary key keeps mutable fields (e.g. total_plays) fresh.
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=BUZZSPROUT_ENDPOINTS[endpoint].should_sync_default,
                description=BUZZSPROUT_ENDPOINTS[endpoint].description,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: BuzzsproutSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_buzzsprout_credentials(config.api_token, config.podcast_id)

    def source_for_pipeline(self, config: BuzzsproutSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return buzzsprout_source(
            api_token=config.api_token,
            podcast_id=config.podcast_id,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
        )
