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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import RailwaySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.railway.railway import (
    RailwayResumeConfig,
    railway_source,
    validate_credentials as validate_railway_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.railway.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class RailwaySource(ResumableSource[RailwaySourceConfig, RailwayResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.RAILWAY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.RAILWAY,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Railway",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Railway API token to pull your Railway projects, services, environments, deployments, members, and volumes into the PostHog Data warehouse.

Create an account or workspace token in your [Railway account settings](https://railway.com/account/tokens). Project tokens are not supported — they are scoped to a single environment and cannot list your projects.

Note that Railway rate limits API requests per plan (as low as 100 requests/hour on the Free plan), which can slow down large initial syncs.""",
            iconPath="/static/services/railway.png",
            docsUrl="https://posthog.com/docs/cdp/sources/railway",
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.railway.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # Railway returns auth failures as HTTP 200 + a GraphQL "Not Authorized" error; the
            # transport re-raises them with this stable prefix. Retrying can never fix a bad token.
            "Railway API error: Not Authorized": "Your Railway API token is invalid, revoked, or lacks access to this resource. Create a new account or workspace token in your Railway account settings, then reconnect.",
        }

    def get_schemas(
        self,
        config: RailwaySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            has_incremental = bool(INCREMENTAL_FIELDS.get(endpoint))
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental,
                # Deployment rows mutate after creation (status, updatedAt), so merge is the only
                # safe write mode — append would materialize stale duplicates.
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                description=(
                    "Incremental syncs page newest-first and stop at the last-seen createdAt. A 24h "
                    "lookback re-pulls recent deployments so late status changes are picked up; older "
                    "status changes only refresh on a full refresh."
                    if endpoint == "deployments"
                    else None
                ),
                # Deployments still building/deploying keep changing status after creation; re-read a
                # trailing day each incremental run so those rows settle without a full refresh.
                default_incremental_lookback_seconds=86400 if endpoint == "deployments" else None,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: RailwaySourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_railway_credentials(config.api_token)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[RailwayResumeConfig]:
        return ResumableSourceManager[RailwayResumeConfig](inputs, RailwayResumeConfig)

    def source_for_pipeline(
        self,
        config: RailwaySourceConfig,
        resumable_source_manager: ResumableSourceManager[RailwayResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return railway_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
