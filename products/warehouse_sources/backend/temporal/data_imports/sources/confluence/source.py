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
from products.warehouse_sources.backend.temporal.data_imports.sources.confluence.confluence import (
    ConfluenceResumeConfig,
    confluence_source,
    validate_credentials as validate_confluence_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.confluence.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ConfluenceSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ConfluenceSource(ResumableSource[ConfluenceSourceConfig, ConfluenceResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://developer.atlassian.com/cloud/confluence/rest/v2/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CONFLUENCE

    @property
    def connection_host_fields(self) -> list[str]:
        # The API token is sent to <subdomain>.atlassian.net, so retargeting the
        # subdomain must force re-entry of the token.
        return ["subdomain"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CONFLUENCE,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Confluence",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Atlassian Confluence Cloud credentials to pull your Confluence content into the PostHog Data warehouse.

Create an API token from your [Atlassian account settings](https://id.atlassian.com/manage-profile/security/api-tokens), then connect using the email address tied to that account.

Only Confluence Cloud sites (`your-domain.atlassian.net`) are supported.""",
            iconPath="/static/services/confluence.png",
            docsUrl="https://posthog.com/docs/cdp/sources/confluence",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="subdomain",
                        label="Subdomain",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="your-domain",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="email",
                        label="Email",
                        type=SourceFieldInputConfigType.EMAIL,
                        required=True,
                        placeholder="you@example.com",
                        secret=False,
                    ),
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.confluence.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: ConfluenceSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                # v2 list endpoints have no server-side timestamp filter, so all
                # endpoints are full refresh only.
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: ConfluenceSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_confluence_credentials(
            subdomain=config.subdomain,
            email=config.email,
            api_token=config.api_token,
            schema_name=schema_name,
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized": "Your Confluence credentials are invalid or expired. Check your email and API token and reconnect.",
            "403 Client Error: Forbidden": "Your Confluence account does not have permission to access this resource.",
        }

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ConfluenceResumeConfig]:
        return ResumableSourceManager[ConfluenceResumeConfig](inputs, ConfluenceResumeConfig)

    def source_for_pipeline(
        self,
        config: ConfluenceSourceConfig,
        resumable_source_manager: ResumableSourceManager[ConfluenceResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return confluence_source(
            subdomain=config.subdomain,
            email=config.email,
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
