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
from products.warehouse_sources.backend.temporal.data_imports.sources.buildkite.buildkite import (
    BuildkiteResumeConfig,
    buildkite_source,
    validate_credentials as validate_buildkite_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.buildkite.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.buildkite.settings import (
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import BuildkiteSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BuildkiteSource(ResumableSource[BuildkiteSourceConfig, BuildkiteResumeConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BUILDKITE

    @property
    def connection_host_fields(self) -> list[str]:
        # The token is sent to api.buildkite.com against <organization>, so retargeting the
        # organization must force re-entry of the token.
        return ["organization"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BUILDKITE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Buildkite",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your Buildkite API access token and organization slug to sync your CI/CD data into the PostHog Data warehouse.

You can create an API access token in your [Buildkite account settings](https://buildkite.com/user/api-access-tokens).

Make sure to grant the following read scopes:
- `read_organizations`
- `read_pipelines`
- `read_builds`
- `read_agents`
""",
            iconPath="/static/services/buildkite.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_access_token",
                        label="API access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="bkua_...",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="organization",
                        label="Organization slug",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="my-organization",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked token surfaces as a requests HTTPError when `_fetch_page` calls
            # `raise_for_status()`. Retrying can't satisfy a credential problem, so stop the sync.
            "401 Client Error: Unauthorized for url: https://api.buildkite.com": "Your Buildkite API access token is invalid or has been revoked. Create a new token in your Buildkite account settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.buildkite.com": "Your Buildkite API access token is missing the read scope needed to sync this data. Grant the required read scopes in your Buildkite account settings, then reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: BuildkiteSourceConfig,
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
        self, config: BuildkiteSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_buildkite_credentials(config.api_access_token, config.organization, schema_name)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[BuildkiteResumeConfig]:
        return ResumableSourceManager[BuildkiteResumeConfig](inputs, BuildkiteResumeConfig)

    def source_for_pipeline(
        self,
        config: BuildkiteSourceConfig,
        resumable_source_manager: ResumableSourceManager[BuildkiteResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return buildkite_source(
            api_access_token=config.api_access_token,
            organization=config.organization,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
