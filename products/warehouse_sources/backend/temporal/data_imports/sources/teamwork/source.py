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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import _is_host_safe
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import TeamworkSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.teamwork.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.teamwork.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    TEAMWORK_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.teamwork.teamwork import (
    TeamworkResumeConfig,
    normalize_host,
    teamwork_source,
    validate_credentials as validate_teamwork_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TeamworkSource(ResumableSource[TeamworkSourceConfig, TeamworkResumeConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TEAMWORK

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TEAMWORK,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Teamwork",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Teamwork.com site and API key to pull your Teamwork projects data into the PostHog Data warehouse.

Find your API key under **Profile → Edit my details → API & Mobile** in Teamwork. The key inherits your own permissions, so it can only sync data you can see.""",
            iconPath="/static/services/teamwork.png",
            docsUrl="https://posthog.com/docs/cdp/sources/teamwork",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="site",
                        label="Site",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="yoursite.teamwork.com",
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
            unreleasedSource=True,
        )

    @property
    def connection_host_fields(self) -> list[str]:
        # The API key is sent to the host derived from `site`; retargeting it must re-require the key.
        return ["site"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Your Teamwork API key is invalid or has been revoked. Generate a new key in your Teamwork profile settings, then reconnect.",
            "403 Client Error: Forbidden for url": "Your Teamwork API key does not have permission to access this data. Check the key's permissions, then reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: TeamworkSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=(inc := INCREMENTAL_FIELDS.get(endpoint)) is not None,
                supports_append=inc is not None,
                incremental_fields=inc or [],
                should_sync_default=TEAMWORK_ENDPOINTS[endpoint].should_sync_default,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: TeamworkSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        host = normalize_host(config.site)

        host_is_safe, host_error = _is_host_safe(host, team_id)
        if not host_is_safe:
            return False, host_error or "Teamwork site host is not allowed"

        if validate_teamwork_credentials(host, config.api_key):
            return True, None

        return False, "Teamwork rejected the credentials. Check the site and API key are correct."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[TeamworkResumeConfig]:
        return ResumableSourceManager[TeamworkResumeConfig](inputs, TeamworkResumeConfig)

    def source_for_pipeline(
        self,
        config: TeamworkSourceConfig,
        resumable_source_manager: ResumableSourceManager[TeamworkResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        host = normalize_host(config.site)

        # Re-check host safety at sync time, not just at source creation: `site` can be edited after
        # validation, and every request below sends the stored API key to it — block internal/private
        # hosts to prevent SSRF and credential redirection.
        host_is_safe, host_error = _is_host_safe(host, inputs.team_id)
        if not host_is_safe:
            raise ValueError(host_error or "Teamwork site host is not allowed")

        return teamwork_source(
            host=host,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
