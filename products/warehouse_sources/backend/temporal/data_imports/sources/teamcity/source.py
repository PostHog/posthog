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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import TeamcitySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.teamcity.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    TEAMCITY_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.teamcity.teamcity import (
    TeamCityResumeConfig,
    teamcity_source,
    validate_credentials as validate_teamcity_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TeamcitySource(ResumableSource[TeamcitySourceConfig, TeamCityResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TEAMCITY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.TEAMCITY,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="JetBrains TeamCity",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your TeamCity server URL and an access token to pull your CI/CD data into the PostHog Data warehouse.

Create an access token under **Your profile → Access Tokens** in TeamCity. The token inherits your user's permissions, so it can read every project and build you can see.""",
            iconPath="/static/services/teamcity.png",
            docsUrl="https://posthog.com/docs/cdp/sources/teamcity",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="host",
                        label="Server URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://teamcity.example.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.teamcity.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # 401/403 surface as a requests HTTPError when `_fetch_page` calls
            # `raise_for_status()`. Retrying can never fix a credential/permission problem.
            "401 Client Error: Unauthorized": "Your TeamCity access token is invalid or has expired. Create a new token under Your profile → Access Tokens, then reconnect.",
            "403 Client Error: Forbidden": "Your TeamCity access token is missing the permissions needed to sync this data. Check the token owner's project view permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: TeamcitySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = TEAMCITY_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                supports_incremental=endpoint_config.supports_incremental,
                supports_append=endpoint_config.supports_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: TeamcitySourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        try:
            ok, status_code = validate_teamcity_credentials(config.host, config.access_token, team_id)
        except ValueError as e:
            return False, str(e)

        if ok:
            return True, None
        if status_code == 401:
            return False, "Invalid TeamCity access token"
        return False, "Could not connect to TeamCity with the provided server URL and access token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[TeamCityResumeConfig]:
        return ResumableSourceManager[TeamCityResumeConfig](inputs, TeamCityResumeConfig)

    def source_for_pipeline(
        self,
        config: TeamcitySourceConfig,
        resumable_source_manager: ResumableSourceManager[TeamCityResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return teamcity_source(
            host=config.host,
            access_token=config.access_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
