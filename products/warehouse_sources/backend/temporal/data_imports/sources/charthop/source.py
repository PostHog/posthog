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
from products.warehouse_sources.backend.temporal.data_imports.sources.charthop.charthop import (
    AUTH_ERROR_HINT,
    ChartHopResumeConfig,
    charthop_source,
    check_access,
    resolve_org_id,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.charthop.settings import (
    CHARTHOP_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ChartHopSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ChartHopSource(ResumableSource[ChartHopSourceConfig, ChartHopResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CHARTHOP

    @property
    def connection_host_fields(self) -> list[str]:
        # `org_id` selects which org the stored API token is used against; retargeting it must
        # re-require the token so an editor can't point the preserved credential at another org.
        return ["org_id"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CHART_HOP,
            category=DataWarehouseSourceCategory.HR___RECRUITING,
            label="ChartHop",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your ChartHop API token to pull your ChartHop people, org chart, and compensation-change data into the PostHog Data warehouse.

You can generate an API token in ChartHop under **Settings → API**. The token's access level determines which data the source can read.

The organization ID (or slug) is optional — it's detected automatically when your token can access exactly one organization.
""",
            docsUrl="https://posthog.com/docs/cdp/sources/charthop",
            iconPath="/static/services/charthop.png",
            keywords=["hr", "people analytics", "org chart", "compensation"],
            unreleasedSource=True,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="org_id",
                        label="Organization ID or slug (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.charthop.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: ChartHopSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=CHARTHOP_ENDPOINTS[endpoint].incremental_param is not None,
                supports_append=CHARTHOP_ENDPOINTS[endpoint].incremental_param is not None,
                incremental_fields=CHARTHOP_ENDPOINTS[endpoint].incremental_fields,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: ChartHopSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if schema_name is not None and schema_name not in CHARTHOP_ENDPOINTS:
            return False, f"Unknown ChartHop schema '{schema_name}'"

        status, message = check_access(config.api_key, config.org_id, schema_name)

        if status == 200:
            return True, None
        if status == 401:
            return False, "Invalid ChartHop API token"
        if status == 403:
            if schema_name is not None:
                return False, f"Your ChartHop API token does not have permission to read '{schema_name}'"
            return False, message or "Your ChartHop API token does not have access to this organization"
        if status == 404 and config.org_id:
            return False, f"ChartHop organization '{config.org_id}' was not found"

        return False, message or "Could not validate ChartHop credentials"

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your ChartHop API token is invalid or expired. Please generate a new token and reconnect.",
            "403 Client Error": "Your ChartHop API token does not have the required permissions. Please check the token's access level and try again.",
            AUTH_ERROR_HINT: "Your ChartHop API token is invalid or lacks the required permissions. Please check the token and try again.",
            "has no access to any organization": "Your ChartHop API token has no access to any organization. Please generate a new token and reconnect.",
            "can access multiple organizations": "Your ChartHop API token can access multiple organizations. Set the organization ID or slug on the source.",
        }

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ChartHopResumeConfig]:
        return ResumableSourceManager[ChartHopResumeConfig](inputs, ChartHopResumeConfig)

    def source_for_pipeline(
        self,
        config: ChartHopSourceConfig,
        resumable_source_manager: ResumableSourceManager[ChartHopResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return charthop_source(
            api_key=config.api_key,
            org_id=resolve_org_id(config.api_key, config.org_id),
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
