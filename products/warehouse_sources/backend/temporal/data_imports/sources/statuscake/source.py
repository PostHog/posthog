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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import StatuscakeSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.statuscake.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    STATUSCAKE_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.statuscake.statuscake import (
    StatusCakeResumeConfig,
    statuscake_source,
    validate_credentials as validate_statuscake_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class StatuscakeSource(ResumableSource[StatuscakeSourceConfig, StatusCakeResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.STATUSCAKE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.STATUSCAKE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="StatusCake",
            caption=(
                "Sync your StatusCake uptime, SSL, pagespeed, and heartbeat monitoring data. "
                "Generate an API token under **[Account Settings > API Keys](https://app.statuscake.com/User.php)** "
                "in your StatusCake dashboard and paste it below. The token has account-wide read access; "
                "no extra scopes are required."
            ),
            iconPath="/static/services/statuscake.png",
            docsUrl="https://posthog.com/docs/cdp/sources/statuscake",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["uptime", "monitoring", "ssl"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Your StatusCake API token",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.statuscake.com": "Your StatusCake API token is invalid or has been revoked. Generate a new token in your StatusCake account settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.statuscake.com": "Your StatusCake API token does not have permission to read this data. Please check the token and reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.statuscake.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: StatuscakeSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _description(endpoint: str) -> str | None:
            if STATUSCAKE_ENDPOINTS[endpoint].fan_out_over is not None:
                return (
                    "Fetched per test, so a sync makes one request chain per test in your account. "
                    "History retention on StatusCake depends on your plan"
                )
            return None

        schemas = [
            SourceSchema(
                name=endpoint,
                # Only the per-test history endpoints expose a server-side `after` timestamp bound;
                # the config/test lists have no changed-since filter and are full refresh only.
                supports_incremental=bool(INCREMENTAL_FIELDS.get(endpoint)),
                supports_append=bool(INCREMENTAL_FIELDS.get(endpoint)),
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=STATUSCAKE_ENDPOINTS[endpoint].should_sync_default,
                description=_description(endpoint),
            )
            for endpoint in list(ENDPOINTS)
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: StatuscakeSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_statuscake_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[StatusCakeResumeConfig]:
        return ResumableSourceManager[StatusCakeResumeConfig](inputs, StatusCakeResumeConfig)

    def source_for_pipeline(
        self,
        config: StatuscakeSourceConfig,
        resumable_source_manager: ResumableSourceManager[StatusCakeResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return statuscake_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
