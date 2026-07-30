from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.coveralls.coveralls import (
    CoverallsResumeConfig,
    coveralls_source,
    validate_credentials as validate_coveralls_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.coveralls.settings import (
    COVERALLS_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import CoverallsSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CoverallsSource(ResumableSource[CoverallsSourceConfig, CoverallsResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.COVERALLS

    @property
    def connection_host_fields(self) -> list[str]:
        # `service` and `repositories` decide which repos the stored `api_token` is sent to query,
        # so retargeting either must re-require the token — otherwise an editor without the token
        # could reuse the preserved one to pull data from repositories it grants access to.
        return ["service", "repositories"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.COVERALLS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Coveralls",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["code coverage", "coverage", "coveralls.io"],
            caption="""Pull per-build code coverage history from [Coveralls](https://coveralls.io) into the PostHog Data warehouse to track coverage trends and catch regressions across repositories.

Enter the repositories you want to track, one per line (or comma-separated), in `owner/repo` form. For example:

```
lemurheavy/coveralls-ruby
posthog/posthog
```

The builds feed is public, so no credentials are needed for public repositories (private repositories are not supported). The optional `repositories` table uses Coveralls' repos API and needs a [personal API token](https://coveralls.io/account) from your Coveralls account settings.""",
            iconPath="/static/services/coveralls.png",
            docsUrl="https://posthog.com/docs/cdp/sources/coveralls",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="service",
                        label="Git service",
                        required=True,
                        defaultValue="github",
                        options=[
                            SourceFieldSelectConfigOption(label="GitHub", value="github"),
                            SourceFieldSelectConfigOption(label="GitLab", value="gitlab"),
                            SourceFieldSelectConfigOption(label="Bitbucket", value="bitbucket"),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="repositories",
                        label="Repositories",
                        type=SourceFieldInputConfigType.TEXTAREA,
                        required=True,
                        placeholder="lemurheavy/coveralls-ruby\nposthog/posthog",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_token",
                        label="Personal API token (optional)",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=False,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.coveralls.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://coveralls.io": "Your Coveralls personal API token is invalid or expired. Create a new token in your Coveralls account settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://coveralls.io": "Your Coveralls personal API token does not have access to this repository. Check the token and repository access, then reconnect.",
        }

    def get_schemas(
        self,
        config: CoverallsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                # The builds feed has no server-side time filter, but it's strictly newest-first, so
                # an incremental sync walks pages only until it reaches the last-seen `created_at`
                # watermark — API cost stays proportional to new builds, not full history.
                supports_incremental=len(INCREMENTAL_FIELDS.get(endpoint, [])) > 0,
                # Incremental runs re-pull a safety window past the watermark; only merge dedupes
                # those on the primary key, append would materialize them as duplicates.
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=COVERALLS_ENDPOINTS[endpoint].should_sync_default,
                description=COVERALLS_ENDPOINTS[endpoint].description,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: CoverallsSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_coveralls_credentials(
            service=config.service,
            repositories_raw=config.repositories,
            api_token=config.api_token,
            schema_name=schema_name,
        )

    def get_endpoint_permissions(
        self, config: CoverallsSourceConfig, team_id: int, endpoints: list[str]
    ) -> dict[str, str | None]:
        permissions: dict[str, str | None] = dict.fromkeys(endpoints)
        for endpoint in endpoints:
            if COVERALLS_ENDPOINTS.get(endpoint) and COVERALLS_ENDPOINTS[endpoint].requires_api_token:
                if not config.api_token:
                    permissions[endpoint] = "Requires a personal API token from your Coveralls account settings."
        return permissions

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[CoverallsResumeConfig]:
        return ResumableSourceManager[CoverallsResumeConfig](inputs, CoverallsResumeConfig)

    def source_for_pipeline(
        self,
        config: CoverallsSourceConfig,
        resumable_source_manager: ResumableSourceManager[CoverallsResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return coveralls_source(
            endpoint=inputs.schema_name,
            service=config.service,
            repositories_raw=config.repositories,
            api_token=config.api_token,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
