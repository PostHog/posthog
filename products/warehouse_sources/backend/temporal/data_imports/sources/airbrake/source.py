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
from products.warehouse_sources.backend.temporal.data_imports.sources.airbrake.airbrake import (
    AirbrakeResumeConfig,
    airbrake_source,
    validate_credentials as validate_airbrake_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.airbrake.settings import (
    AIRBRAKE_ENDPOINTS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import AirbrakeSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AirbrakeSource(ResumableSource[AirbrakeSourceConfig, AirbrakeResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AIRBRAKE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.AIRBRAKE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Airbrake",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Airbrake user API key to pull your Airbrake error monitoring data into the PostHog Data warehouse.

You can find your user key in your Airbrake profile settings under **User settings**. All projects the key can access are synced.
""",
            iconPath="/static/services/airbrake.png",
            docsUrl="https://posthog.com/docs/cdp/sources/airbrake",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="User API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.airbrake.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # Auth failures surface as a requests HTTPError from `raise_for_status()`. Match the
            # stable status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.airbrake.io": "Your Airbrake user API key is invalid or has been revoked. Generate a new key in your Airbrake user settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.airbrake.io": "Your Airbrake user API key does not have access to this data. Check the key's project access in Airbrake, then reconnect.",
        }

    def get_schemas(
        self,
        config: AirbrakeSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _description(endpoint: str) -> str | None:
            if endpoint == "groups":
                return (
                    "Incremental syncs only pick up newly created error groups; fields that mutate on "
                    "existing groups (noticeCount, resolved, lastNoticeAt) are only refreshed by a full refresh"
                )
            if endpoint == "notices":
                return (
                    "Individual error occurrences, fetched per error group across every project — the most "
                    "API-expensive table, capped at the most recent pages per group"
                )
            return None

        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=len(INCREMENTAL_FIELDS.get(endpoint, [])) > 0,
                supports_append=len(INCREMENTAL_FIELDS.get(endpoint, [])) > 0,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=AIRBRAKE_ENDPOINTS[endpoint].should_sync_default,
                description=_description(endpoint),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: AirbrakeSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_airbrake_credentials(config.api_key):
            return True, None

        return False, "Invalid Airbrake user API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AirbrakeResumeConfig]:
        return ResumableSourceManager[AirbrakeResumeConfig](inputs, AirbrakeResumeConfig)

    def source_for_pipeline(
        self,
        config: AirbrakeSourceConfig,
        resumable_source_manager: ResumableSourceManager[AirbrakeResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return airbrake_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
