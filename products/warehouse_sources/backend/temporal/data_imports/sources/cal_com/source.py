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
from products.warehouse_sources.backend.temporal.data_imports.sources.cal_com.cal_com import (
    CalComResumeConfig,
    cal_com_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cal_com.settings import (
    CAL_COM_ENDPOINTS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CalComSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CalComSource(ResumableSource[CalComSourceConfig, CalComResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CALCOM

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CAL_COM,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Cal.com",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Cal.com API key to pull your scheduling data into the PostHog Data warehouse.

You can create an API key under **Settings → Security → API keys** in [Cal.com](https://app.cal.com/settings/developer/api-keys). The key grants read access to your bookings, event types, schedules, teams, and webhooks.
""",
            iconPath="/static/services/cal_com.png",
            docsUrl="https://posthog.com/docs/cdp/sources/cal-com",
            keywords=["calcom", "scheduling", "booking"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="cal_live_...",
                        secret=True,
                    ),
                ],
            ),
            unreleasedSource=True,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.cal_com.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.cal.com": "Your Cal.com API key is invalid or has been revoked. Create a new API key under Settings → Security → API keys in Cal.com, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.cal.com": "Your Cal.com API key does not have access to this data. Check the key owner's permissions in Cal.com, then reconnect.",
        }

    def get_schemas(
        self,
        config: CalComSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Only bookings exposes server-side timestamp filters (afterUpdatedAt / afterCreatedAt), so
        # it is the only endpoint that supports incremental sync.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=bool(INCREMENTAL_FIELDS.get(endpoint)),
                supports_append=bool(INCREMENTAL_FIELDS.get(endpoint)),
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: CalComSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The API key is account-wide, so a single probe validates access to every schema.
        return validate_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CalComResumeConfig]:
        return ResumableSourceManager[CalComResumeConfig](inputs, CalComResumeConfig)

    def source_for_pipeline(
        self,
        config: CalComSourceConfig,
        resumable_source_manager: ResumableSourceManager[CalComResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in CAL_COM_ENDPOINTS:
            raise ValueError(f"Unknown Cal.com schema '{inputs.schema_name}'")

        return cal_com_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
