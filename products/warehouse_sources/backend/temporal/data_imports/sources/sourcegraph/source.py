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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SourcegraphSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.sourcegraph.settings import (
    ENDPOINTS,
    SOURCEGRAPH_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sourcegraph.sourcegraph import (
    HOST_NOT_ALLOWED_ERROR,
    SourcegraphResumeConfig,
    get_endpoint_permissions as get_sourcegraph_endpoint_permissions,
    sourcegraph_source,
    validate_credentials as validate_sourcegraph_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SourcegraphSource(ResumableSource[SourcegraphSourceConfig, SourcegraphResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SOURCEGRAPH

    @property
    def connection_host_fields(self) -> list[str]:
        # The access token is sent to whatever host `host` points at, so retargeting
        # it must re-require the token (prevents credential exfiltration to another host).
        return ["host"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SOURCEGRAPH,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Sourcegraph",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Sourcegraph instance URL and an access token to pull your Sourcegraph data into the PostHog Data warehouse.

You can create an access token in Sourcegraph under **Settings > Access tokens**.

The `users` and `organizations` tables require a token created by a **site admin**; `repositories` works with any user's token.
""",
            iconPath="/static/services/sourcegraph.png",
            docsUrl="https://posthog.com/docs/cdp/sources/sourcegraph",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="host",
                        label="Sourcegraph URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://sourcegraph.example.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="sgp_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid Sourcegraph access token. Please generate a new token and reconnect.",
            "403 Client Error": "Your Sourcegraph access token lacks the required permissions. Please check the token and try again.",
            "Sourcegraph GraphQL error: not authenticated": "Your Sourcegraph access token is not authenticated for this data. Please generate a new token and reconnect.",
            "Sourcegraph GraphQL error: must be site admin": "This table requires a site-admin access token. Please reconnect with a token created by a Sourcegraph site admin.",
            HOST_NOT_ALLOWED_ERROR: "The Sourcegraph URL is not allowed. Please use your organization's Sourcegraph instance URL.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.sourcegraph.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: SourcegraphSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # No Sourcegraph connection exposes a server-side updated-since filter, so every
        # endpoint is full-refresh only (the cursor still makes runs resumable mid-sync).
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
                description=SOURCEGRAPH_ENDPOINTS[endpoint].description,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: SourcegraphSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_sourcegraph_credentials(config.host, config.access_token, schema_name, team_id)

    def get_endpoint_permissions(
        self, config: SourcegraphSourceConfig, team_id: int, endpoints: list[str]
    ) -> dict[str, str | None]:
        return get_sourcegraph_endpoint_permissions(config.host, config.access_token, team_id, endpoints)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SourcegraphResumeConfig]:
        return ResumableSourceManager[SourcegraphResumeConfig](inputs, SourcegraphResumeConfig)

    def source_for_pipeline(
        self,
        config: SourcegraphSourceConfig,
        resumable_source_manager: ResumableSourceManager[SourcegraphResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return sourcegraph_source(
            host=config.host,
            access_token=config.access_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            team_id=inputs.team_id,
        )
