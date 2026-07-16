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
from products.warehouse_sources.backend.temporal.data_imports.sources.better_stack.better_stack import (
    BetterStackResumeConfig,
    better_stack_source,
    probe_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.better_stack.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.better_stack.settings import (
    BETTER_STACK_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import BetterStackSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BetterStackSource(ResumableSource[BetterStackSourceConfig, BetterStackResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BETTERSTACK

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BETTER_STACK,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Better Stack",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Better Stack API token to automatically pull your uptime monitoring and incident data into the PostHog Data warehouse.

You can create an Uptime API token in your [Better Stack dashboard](https://uptime.betterstack.com) under Integrations → API tokens. A team-scoped token syncs that team's data; a global token spans all teams.""",
            iconPath="/static/services/better_stack.png",
            docsUrl="https://posthog.com/docs/cdp/sources/better-stack",
            keywords=["betterstack", "better uptime"],
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
        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # 401/403 surface as a requests HTTPError when `_fetch_page` calls `raise_for_status()`.
            # No retry can satisfy a credential problem. Match the stable status text + base host,
            # not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://uptime.betterstack.com": "Your Better Stack API token is invalid or has been revoked. Create a new Uptime API token in your Better Stack dashboard, then reconnect.",
            "403 Client Error: Forbidden for url: https://uptime.betterstack.com": "Your Better Stack API token does not have access to this resource. Check the token's team scope in your Better Stack dashboard, then reconnect.",
        }

    def get_schemas(
        self,
        config: BetterStackSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(
            ENDPOINTS,
            {name: endpoint_config.incremental_fields for name, endpoint_config in BETTER_STACK_ENDPOINTS.items()},
            names,
            should_sync_default={
                name: endpoint_config.should_sync_default for name, endpoint_config in BETTER_STACK_ENDPOINTS.items()
            },
        )

    def validate_credentials(
        self, config: BetterStackSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        status = probe_credentials(config.api_token, schema_name)

        if status == 200:
            return True, None
        # At source-create (schema_name is None) a 403 means the token is genuine but scoped away
        # from the probe resource — accept it; per-endpoint scope is checked when configuring a schema.
        if status == 403 and schema_name is None:
            return True, None
        if status == 401:
            return False, "Your Better Stack API token is invalid or has been revoked."
        if status == 403:
            return False, "Your Better Stack API token does not have access to this resource."
        return False, "Could not validate your Better Stack API token. Please check the token and try again."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[BetterStackResumeConfig]:
        return ResumableSourceManager[BetterStackResumeConfig](inputs, BetterStackResumeConfig)

    def source_for_pipeline(
        self,
        config: BetterStackSourceConfig,
        resumable_source_manager: ResumableSourceManager[BetterStackResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return better_stack_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
