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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SquadcastSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.squadcast.settings import (
    ENDPOINTS,
    SQUADCAST_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.squadcast.squadcast import (
    SquadcastResumeConfig,
    squadcast_source,
    validate_credentials as validate_squadcast_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SquadcastSource(ResumableSource[SquadcastSourceConfig, SquadcastResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SQUADCAST

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SQUADCAST,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Squadcast (SolarWinds Incident Response)",
            keywords=["solarwinds", "incident response", "on-call", "oncall"],
            caption="""Enter your Squadcast refresh token to pull your incident response data into the PostHog Data warehouse.

You can generate a refresh token from your Squadcast profile page (**Profile → Refresh Token**). PostHog exchanges it for a short-lived access token on each sync.

The token inherits your user role, so the connecting user needs read access to the teams and resources you want to sync.""",
            iconPath="/static/services/squadcast.png",
            docsUrl="https://posthog.com/docs/cdp/sources/squadcast",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="refresh_token",
                        label="Refresh token",
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
                            SourceFieldSelectConfigOption(label="US (api.squadcast.com)", value="us"),
                            SourceFieldSelectConfigOption(label="EU (api.eu.squadcast.com)", value="eu"),
                        ],
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.squadcast.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: SquadcastSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # supports_append=False everywhere: incidents and postmortems mutate after creation and
        # incremental windows re-pull boundary rows, so only merge semantics dedupe correctly.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=bool(SQUADCAST_ENDPOINTS[endpoint].incremental_fields),
                supports_append=False,
                incremental_fields=SQUADCAST_ENDPOINTS[endpoint].incremental_fields,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: SquadcastSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        ok, status, error = validate_squadcast_credentials(config.refresh_token, config.region, schema_name)
        if ok:
            return True, None

        # A valid token may legitimately lack access to a specific resource (the token inherits
        # the user's role). Accept 403 at source-create so users can connect with a lower-role
        # account; re-raise it for per-schema checks.
        if status == 403 and schema_name is None:
            return True, None

        return False, error

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "Squadcast refresh token was rejected": "Your Squadcast refresh token is invalid or expired. Generate a new refresh token from your Squadcast profile page and reconnect.",
            "401 Client Error: Unauthorized for url: https://api.squadcast.com": "Your Squadcast refresh token is invalid or expired. Generate a new refresh token from your Squadcast profile page and reconnect.",
            "401 Client Error: Unauthorized for url: https://api.eu.squadcast.com": "Your Squadcast refresh token is invalid or expired. Generate a new refresh token from your Squadcast profile page and reconnect.",
            "403 Client Error: Forbidden for url: https://api.squadcast.com": "Your Squadcast account does not have the permissions needed to sync this data. The token inherits your user role, so reconnect with an account that can read these resources.",
            "403 Client Error: Forbidden for url: https://api.eu.squadcast.com": "Your Squadcast account does not have the permissions needed to sync this data. The token inherits your user role, so reconnect with an account that can read these resources.",
        }

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SquadcastResumeConfig]:
        return ResumableSourceManager[SquadcastResumeConfig](inputs, SquadcastResumeConfig)

    def source_for_pipeline(
        self,
        config: SquadcastSourceConfig,
        resumable_source_manager: ResumableSourceManager[SquadcastResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return squadcast_source(
            refresh_token=config.refresh_token,
            region=config.region,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
