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
from products.warehouse_sources.backend.temporal.data_imports.sources.clockodo.clockodo import (
    ClockodoResumeConfig,
    clockodo_source,
    validate_credentials as validate_clockodo_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clockodo.settings import (
    CLOCKODO_ENDPOINTS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ClockodoSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ClockodoSource(ResumableSource[ClockodoSourceConfig, ClockodoResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CLOCKODO

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # Clockodo returns 401 both for a bad API user/key and for a missing identification
            # header; retrying can never fix either, so stop the sync. Match the stable status text
            # and base host, not the per-request path.
            "401 Client Error: Unauthorized for url: https://my.clockodo.com": "Your Clockodo email or API key is invalid. Find your API key under Personal data in Clockodo, then reconnect.",
            "403 Client Error: Forbidden for url: https://my.clockodo.com": "Your Clockodo user does not have permission to read this data. Clockodo credentials are scoped per co-worker — check the user's permissions, then reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.clockodo.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: ClockodoSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Clockodo exposes no server-side modified-since filter, so every table is full refresh only.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=CLOCKODO_ENDPOINTS[endpoint].should_sync_default,
                description=CLOCKODO_ENDPOINTS[endpoint].description,
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: ClockodoSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_clockodo_credentials(config.api_user, config.api_key):
            return True, None

        return False, "Invalid Clockodo credentials"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ClockodoResumeConfig]:
        return ResumableSourceManager[ClockodoResumeConfig](inputs, ClockodoResumeConfig)

    def source_for_pipeline(
        self,
        config: ClockodoSourceConfig,
        resumable_source_manager: ResumableSourceManager[ClockodoResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return clockodo_source(
            api_user=config.api_user,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CLOCKODO,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Clockodo",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your Clockodo email and API key to pull your Clockodo time-tracking data into the PostHog Data warehouse.

You can find your personal API key under **Personal data** in your Clockodo account. Credentials are scoped to that co-worker's permissions, so connect a user that can see the data you want to sync.""",
            iconPath="/static/services/clockodo.png",
            docsUrl="https://posthog.com/docs/cdp/sources/clockodo",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_user",
                        label="Email",
                        type=SourceFieldInputConfigType.EMAIL,
                        required=True,
                        placeholder="you@example.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )
