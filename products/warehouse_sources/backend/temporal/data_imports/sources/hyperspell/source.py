from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import HyperspellSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.hyperspell.hyperspell import (
    HyperspellResumeConfig,
    hyperspell_source,
    validate_credentials as validate_hyperspell_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hyperspell.settings import (
    ENDPOINTS,
    HYPERSPELL_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class HyperspellSource(ResumableSource[HyperspellSourceConfig, HyperspellResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HYPERSPELL

    @property
    def connection_host_fields(self) -> list[str]:
        # The stored API key is sent to the host derived from `region`, so retargeting the
        # region must re-require the key rather than reusing it against a different host.
        # `user_ids` is the upstream identity the key acts as (via X-As-User); changing it
        # must also re-require the key so an editor without the credential can't retarget the
        # stored key at other users' data.
        return ["region", "user_ids"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.HYPERSPELL,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Hyperspell",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Hyperspell API key to pull your app's memories, connections, and extracted entities into the PostHog Data warehouse.

Create an API key in the [Hyperspell dashboard](https://app.hyperspell.com/). Keys are region-specific, so pick the region your Hyperspell app lives in.

Memories and connections are scoped to individual users of your Hyperspell app. To sync them, list the user IDs to sync as a comma-separated list — each is fetched via Hyperspell's `X-As-User` header. Leaving it empty syncs app-level data only.
""",
            iconPath="/static/services/hyperspell.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/hyperspell",
            keywords=["ai", "memory", "agents", "context"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="us",
                        options=[
                            SourceFieldSelectConfigOption(label="US (api.hyperspell.com)", value="us"),
                            SourceFieldSelectConfigOption(label="EU (api.eu.hyperspell.com)", value="eu"),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="user_ids",
                        label="User IDs (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="user-1, user-2",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.hyperspell.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: HyperspellSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # No Hyperspell list endpoint exposes a server-side timestamp filter, so every
        # table is full refresh only.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
                detected_primary_keys=HYPERSPELL_ENDPOINTS[endpoint].primary_keys,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: HyperspellSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_hyperspell_credentials(config.api_key, config.region, schema_name)

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized": "Your Hyperspell API key is invalid, expired, or for a different region. Please check the key and region, then reconnect.",
            "403 Client Error: Forbidden": "Your Hyperspell API key was not accepted. Please generate a new key in the Hyperspell dashboard and reconnect.",
        }

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[HyperspellResumeConfig]:
        return ResumableSourceManager[HyperspellResumeConfig](inputs, HyperspellResumeConfig)

    def source_for_pipeline(
        self,
        config: HyperspellSourceConfig,
        resumable_source_manager: ResumableSourceManager[HyperspellResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return hyperspell_source(
            api_key=config.api_key,
            region=config.region,
            user_ids=config.user_ids,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
