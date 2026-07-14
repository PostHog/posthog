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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import NetlifySourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.netlify.netlify import (
    NetlifyResumeConfig,
    netlify_source,
    validate_credentials as validate_netlify_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.netlify.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    NETLIFY_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class NetlifySource(ResumableSource[NetlifySourceConfig, NetlifyResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NETLIFY

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.NETLIFY,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Netlify",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your Netlify personal access token to sync your Netlify data into the PostHog Data warehouse.

Create a personal access token under **User settings > Applications > Personal access tokens** in the [Netlify UI](https://app.netlify.com/user/applications). The token has full access to the resources your account can reach, so no extra scopes are needed.
""",
            iconPath="/static/services/netlify.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/netlify",
            keywords=["hosting", "jamstack", "deploys", "web"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="Personal access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="nfp_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.netlify.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # An invalid or revoked token surfaces as a requests HTTPError when `_fetch_page` calls
            # `raise_for_status()`. Retrying can never satisfy a credential problem, so stop the sync.
            # Match the stable status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.netlify.com": "Your Netlify personal access token is invalid or has been revoked. Netlify invalidates tokens on password reset. Create a new token in your Netlify user settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.netlify.com": "Your Netlify personal access token does not have access to this resource. Create a token with the required access, then reconnect.",
        }

    def get_schemas(
        self,
        config: NetlifySourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Netlify exposes no server-side timestamp filter, so every table is full refresh.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=NETLIFY_ENDPOINTS[endpoint].should_sync_default,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: NetlifySourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_netlify_credentials(config.api_token):
            return True, None

        return False, "Invalid Netlify personal access token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[NetlifyResumeConfig]:
        return ResumableSourceManager[NetlifyResumeConfig](inputs, NetlifyResumeConfig)

    def source_for_pipeline(
        self,
        config: NetlifySourceConfig,
        resumable_source_manager: ResumableSourceManager[NetlifyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return netlify_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
