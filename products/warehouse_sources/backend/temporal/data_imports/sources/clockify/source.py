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
from products.warehouse_sources.backend.temporal.data_imports.sources.clockify.clockify import (
    ClockifyResumeConfig,
    clockify_source,
    validate_credentials as validate_clockify_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clockify.settings import (
    CLOCKIFY_ENDPOINTS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ClockifySourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ClockifySource(ResumableSource[ClockifySourceConfig, ClockifyResumeConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CLOCKIFY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CLOCKIFY,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Clockify",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your Clockify API key to sync your Clockify data into the PostHog Data warehouse.

You can generate an API key on your [Clockify profile settings](https://app.clockify.me/user/settings) page.

The key is user-scoped — it can read exactly what your Clockify user can. Use an admin or owner key to sync workspace-wide data (projects, clients, every member's time entries).""",
            iconPath="/static/services/clockify.png",
            docsUrl="https://posthog.com/docs/cdp/sources/clockify",
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

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # An invalid/revoked key surfaces as a requests HTTPError when `_fetch_page` calls
        # `raise_for_status()`. Match the stable status text and base host, not the per-request
        # path/query. Clockify keys carry no per-endpoint scopes, so a 403 is a credential problem
        # too (e.g. a non-admin key reaching workspace-wide data).
        return {
            "401 Client Error: Unauthorized for url: https://api.clockify.me": "Your Clockify API key is invalid or has been revoked. Generate a new key in your Clockify profile settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.clockify.me": "Your Clockify API key lacks the permissions needed to sync this data. Use an admin or owner key, then reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.clockify.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: ClockifySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            # Only time_entries has a server-side timestamp filter; everything else is full refresh.
            has_incremental = len(INCREMENTAL_FIELDS.get(endpoint, [])) > 0
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental,
                supports_append=has_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=CLOCKIFY_ENDPOINTS[endpoint].should_sync_default,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: ClockifySourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_clockify_credentials(config.api_key):
            return True, None

        return False, "Invalid Clockify API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ClockifyResumeConfig]:
        return ResumableSourceManager[ClockifyResumeConfig](inputs, ClockifyResumeConfig)

    def source_for_pipeline(
        self,
        config: ClockifySourceConfig,
        resumable_source_manager: ResumableSourceManager[ClockifyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return clockify_source(
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
