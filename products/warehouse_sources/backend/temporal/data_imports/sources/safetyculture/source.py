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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SafetyCultureSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.safetyculture.safetyculture import (
    SafetyCultureResumeConfig,
    check_access,
    safetyculture_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.safetyculture.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    SAFETYCULTURE_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SafetyCultureSource(ResumableSource[SafetyCultureSourceConfig, SafetyCultureResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SAFETYCULTURE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SAFETY_CULTURE,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="SafetyCulture",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your SafetyCulture API token to pull your inspections, actions, issues, assets, and workplace-operations data into the PostHog Data warehouse.

You can generate an API token under **Account settings → Integrations → Manage API tokens** in [SafetyCulture](https://app.safetyculture.com) (requires a Premium or Enterprise plan). Tokens expire after 30 days of inactivity, so SafetyCulture recommends a [service user](https://help.safetyculture.com/en-US/1064186-service-users) token with the **Data Access** permission for long-term integrations.
""",
            iconPath="/static/services/safetyculture.png",
            docsUrl="https://posthog.com/docs/cdp/sources/safetyculture",
            keywords=["iauditor", "ehs", "inspections"],
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
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.safetyculture.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.safetyculture.io": "Your SafetyCulture API token is invalid or has expired (tokens expire after 30 days of inactivity). Generate a new token — ideally for a service user — then reconnect.",
            "403 Client Error: Forbidden for url: https://api.safetyculture.io": "Your SafetyCulture API token does not have access to this data. Grant the token's user the Data Access permission, then reconnect.",
        }

    def get_schemas(
        self,
        config: SafetyCultureSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = SAFETYCULTURE_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                supports_incremental=endpoint_config.supports_incremental,
                supports_append=endpoint_config.supports_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: SafetyCultureSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if schema_name is not None and schema_name in SAFETYCULTURE_ENDPOINTS:
            # Per-schema check: the feed this schema syncs must actually be reachable.
            status, message = check_access(config.api_token, SAFETYCULTURE_ENDPOINTS[schema_name].path)
            if status == 200:
                return True, None
            if status in (401, 403):
                return False, f"Your SafetyCulture API token cannot access the {schema_name} feed"
            return False, message or "Could not validate SafetyCulture API token"

        status, message = check_access(config.api_token)
        if status == 200:
            return True, None
        if status == 401:
            return False, "Invalid SafetyCulture API token"
        if status == 403:
            # The token is genuine but its user lacks permission on the probe feed — feed access is
            # permission-scoped, so don't block source-create over one unreachable feed.
            return True, None
        return False, message or "Could not validate SafetyCulture API token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SafetyCultureResumeConfig]:
        return ResumableSourceManager[SafetyCultureResumeConfig](inputs, SafetyCultureResumeConfig)

    def source_for_pipeline(
        self,
        config: SafetyCultureSourceConfig,
        resumable_source_manager: ResumableSourceManager[SafetyCultureResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in SAFETYCULTURE_ENDPOINTS:
            raise ValueError(f"Unknown SafetyCulture schema '{inputs.schema_name}'")

        return safetyculture_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
