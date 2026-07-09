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
from products.warehouse_sources.backend.temporal.data_imports.sources.blogger.blogger import (
    BloggerResumeConfig,
    blogger_source,
    validate_credentials as validate_blogger_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.blogger.settings import (
    BLOGGER_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import BloggerSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BloggerSource(ResumableSource[BloggerSourceConfig, BloggerResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BLOGGER

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BLOGGER,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Blogger",
            releaseStatus=ReleaseStatus.ALPHA,
            # Kept hidden for now: shipping in alpha behind the unreleased flag until it has had
            # an end-to-end sync verified against the live API with real credentials.
            unreleasedSource=True,
            caption="""Enter a Google API key and a Blogger blog ID to pull your Blogger content into the PostHog Data warehouse.

Create an API key in the [Google Cloud console](https://console.cloud.google.com/apis/credentials) and enable the **Blogger API v3** for the project.

Your blog ID is shown in the Blogger dashboard URL (`blogger.com/blog/posts/<blogId>`).

The API key reads publicly visible content (live posts, pages, and comments). Drafts and admin-only data require OAuth, which isn't supported yet.""",
            iconPath="/static/services/blogger.png",
            docsUrl="https://posthog.com/docs/cdp/sources/blogger",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="AIza...",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="blog_id",
                        label="Blog ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="1234567890123456789",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.blogger.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # A missing/invalid API key, a key not authorized for the Blogger API, or a private blog all
            # surface as a non-2xx HTTPError once `_fetch_page` calls `raise_for_status()`. Retrying can
            # never fix a credential/permission problem, so stop the sync. Match on the stable base host.
            "400 Client Error: Bad Request for url: https://www.googleapis.com/blogger/v3": "Your Blogger API key is invalid. Create a new key in the Google Cloud console with the Blogger API enabled, then reconnect.",
            "401 Client Error: Unauthorized for url: https://www.googleapis.com/blogger/v3": "Your Blogger API key is invalid or has been revoked. Create a new key in the Google Cloud console, then reconnect.",
            "403 Client Error: Forbidden for url: https://www.googleapis.com/blogger/v3": "Your Blogger API key cannot access this blog. Enable the Blogger API for your Google Cloud project and confirm the blog is publicly visible, then reconnect.",
        }

    def get_schemas(
        self,
        config: BloggerSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = BLOGGER_ENDPOINTS[endpoint]
            return SourceSchema(
                name=endpoint,
                supports_incremental=endpoint_config.supports_incremental,
                supports_append=endpoint_config.supports_incremental,
                incremental_fields=endpoint_config.incremental_fields,
                should_sync_default=endpoint_config.should_sync_default,
                detected_primary_keys=endpoint_config.primary_keys,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: BloggerSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_blogger_credentials(config.api_key, config.blog_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[BloggerResumeConfig]:
        return ResumableSourceManager[BloggerResumeConfig](inputs, BloggerResumeConfig)

    def source_for_pipeline(
        self,
        config: BloggerSourceConfig,
        resumable_source_manager: ResumableSourceManager[BloggerResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return blogger_source(
            api_key=config.api_key,
            blog_id=config.blog_id,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
