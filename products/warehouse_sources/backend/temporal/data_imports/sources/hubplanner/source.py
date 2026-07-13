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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import HubplannerSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.hubplanner.hubplanner import (
    HubPlannerResumeConfig,
    hubplanner_source,
    validate_credentials as validate_hubplanner_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.hubplanner.settings import (
    ENDPOINTS,
    HUBPLANNER_ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class HubplannerSource(ResumableSource[HubplannerSourceConfig, HubPlannerResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.HUBPLANNER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.HUBPLANNER,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Hub Planner",
            caption="""Enter your Hub Planner API key to sync your resource-scheduling, project-planning and time-tracking data into the PostHog Data warehouse.

Generate a **Read Only** API key in Hub Planner under **Settings → API** (admin access required).""",
            iconPath="/static/services/hubplanner.png",
            docsUrl="https://posthog.com/docs/cdp/sources/hubplanner",
            unreleasedSource=True,
            releaseStatus=ReleaseStatus.ALPHA,
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
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.hubplanner.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # Both a missing/invalid key and an under-permissioned key surface as 403 from Hub Planner
        # (there's no 401 path). Retrying can never satisfy a credential problem, so stop the sync.
        return {
            "403 Client Error: Forbidden for url: https://api.hubplanner.com": "Your Hub Planner API key is invalid or lacks the required permissions. Generate a new Read Only key under Settings → API, then reconnect.",
            "401 Client Error: Unauthorized for url: https://api.hubplanner.com": "Your Hub Planner API key is invalid or has been revoked. Generate a new key under Settings → API, then reconnect.",
        }

    def get_schemas(
        self,
        config: HubplannerSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = HUBPLANNER_ENDPOINTS[endpoint]
            has_incremental = endpoint_config.incremental_search_field is not None
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental,
                supports_append=has_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: HubplannerSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_hubplanner_credentials(config.api_key):
            return True, None

        return False, "Invalid Hub Planner API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[HubPlannerResumeConfig]:
        return ResumableSourceManager[HubPlannerResumeConfig](inputs, HubPlannerResumeConfig)

    def source_for_pipeline(
        self,
        config: HubplannerSourceConfig,
        resumable_source_manager: ResumableSourceManager[HubPlannerResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return hubplanner_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
