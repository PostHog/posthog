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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import VercelSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.vercel.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.vercel.vercel import (
    VercelResumeConfig,
    validate_credentials as validate_vercel_credentials,
    vercel_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class VercelSource(ResumableSource[VercelSourceConfig, VercelResumeConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.VERCEL

    @property
    def connection_host_fields(self) -> list[str]:
        # `team_id` selects which Vercel team the stored access token is used against. Editing it
        # on an existing source must force the token to be re-entered — otherwise an editor could
        # retarget the preserved token at another Vercel team it can access.
        return ["team_id"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.VERCEL,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Vercel",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter a Vercel access token to pull your Vercel deployments, projects, teams, domains, and aliases into the PostHog Data warehouse.

Create an access token in your [Vercel account settings](https://vercel.com/account/tokens). A read-only token is sufficient.

To sync resources owned by a team, also enter the team's ID (found under **Team Settings**). Leave it blank to sync resources owned by the token's user.""",
            iconPath="/static/services/vercel.png",
            docsUrl="https://posthog.com/docs/cdp/sources/vercel",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="team_id",
                        label="Team ID (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="team_...",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.vercel.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # 401/403 surface as a requests HTTPError when `_fetch_page` calls raise_for_status().
            # Retrying never satisfies a credential/permission problem, so stop the sync. Match the
            # stable status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.vercel.com": "Your Vercel access token is invalid or has been revoked. Create a new token in your Vercel account settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.vercel.com": "Your Vercel access token is not authorized for this resource. Check the token's scope (and team access), then reconnect.",
        }

    def get_schemas(
        self,
        config: VercelSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
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
        self, config: VercelSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_vercel_credentials(config.access_token)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[VercelResumeConfig]:
        return ResumableSourceManager[VercelResumeConfig](inputs, VercelResumeConfig)

    def source_for_pipeline(
        self,
        config: VercelSourceConfig,
        resumable_source_manager: ResumableSourceManager[VercelResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return vercel_source(
            access_token=config.access_token,
            endpoint=inputs.schema_name,
            team_id=config.team_id,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
