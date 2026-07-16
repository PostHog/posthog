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
from products.warehouse_sources.backend.temporal.data_imports.sources.bettermode.bettermode import (
    BettermodeResumeConfig,
    bettermode_source,
    validate_credentials as validate_bettermode_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bettermode.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import BettermodeSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BettermodeSource(ResumableSource[BettermodeSourceConfig, BettermodeResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BETTERMODE

    @property
    def connection_host_fields(self) -> list[str]:
        # `region` picks the host the stored client secret is sent to, and `network_id` selects
        # which community the minted token is scoped to; retargeting either must re-require the
        # secret so a preserved credential can't be aimed elsewhere without re-entry.
        return ["region", "network_id"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BETTERMODE,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="Bettermode",
            keywords=["tribe", "community"],
            caption="""Connect your Bettermode (formerly Tribe) community to pull members, spaces, posts, replies, tags, and moderation items into the PostHog Data warehouse.

Create an app in the [Bettermode developer portal](https://developers.bettermode.com/), then copy its client ID and client secret. The app must be **published and installed on your community** before tokens can be issued.

Your network ID is your community's unique ID, shown in the developer portal for your community.

If your community is hosted in the EU (eu-central-1), select the EU region so requests go to Bettermode's EU endpoint.""",
            iconPath="/static/services/bettermode.png",
            docsUrl="https://posthog.com/docs/cdp/sources/bettermode",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="us",
                        options=[
                            SourceFieldSelectConfigOption(label="US (api.bettermode.com)", value="us"),
                            SourceFieldSelectConfigOption(label="EU (api.bettermode.de)", value="eu"),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="client_id",
                        label="Client ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="client_secret",
                        label="Client secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="network_id",
                        label="Network ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.bettermode.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # Bettermode returns GraphQL errors in HTTP 200 bodies; the transport re-raises
            # them with a stable `Bettermode API error (status N)` prefix.
            "Bettermode API error (status 401)": "Bettermode rejected the credentials. Check your client ID, client secret, and network ID, then reconnect.",
            "Bettermode API error (status 403)": "Your Bettermode app doesn't have access to this community. Make sure the app is published and installed on the community, then reconnect.",
            "App not found": "Bettermode couldn't find an app with this client ID. Check the client ID and client secret from the developer portal, then reconnect.",
        }

    def get_schemas(
        self,
        config: BettermodeSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _description(endpoint: str) -> str | None:
            if endpoint == "replies":
                return (
                    "Fetches direct replies of every post that has replies (one request per post), "
                    "so syncs scale with the number of posts in the community"
                )
            return None

        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint) is not None,
                supports_append=INCREMENTAL_FIELDS.get(endpoint) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                description=_description(endpoint),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: BettermodeSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        is_valid, error = validate_bettermode_credentials(
            config.region, config.client_id, config.client_secret, config.network_id
        )
        if is_valid:
            return True, None

        return False, error or "Invalid Bettermode credentials"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[BettermodeResumeConfig]:
        return ResumableSourceManager[BettermodeResumeConfig](inputs, BettermodeResumeConfig)

    def source_for_pipeline(
        self,
        config: BettermodeSourceConfig,
        resumable_source_manager: ResumableSourceManager[BettermodeResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return bettermode_source(
            region=config.region,
            client_id=config.client_id,
            client_secret=config.client_secret,
            network_id=config.network_id,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
