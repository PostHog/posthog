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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import WordpressSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.wordpress.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.wordpress.wordpress import (
    HOST_NOT_ALLOWED_ERROR,
    HTTP_NOT_ALLOWED_ERROR,
    WordpressResumeConfig,
    validate_credentials as validate_wordpress_credentials,
    wordpress_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class WordpressSource(ResumableSource[WordpressSourceConfig, WordpressResumeConfig]):
    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WORDPRESS

    @property
    def connection_host_fields(self) -> list[str]:
        # `site_url` is where any stored application password is sent; retargeting it must re-require
        # the credentials so a member can't point them at a server they control.
        return ["site_url"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.WORDPRESS,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="WordPress",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Sync posts, pages, comments, media, categories, tags, and users from a self-hosted WordPress site via the core REST API (`/wp-json/wp/v2`).

Enter your site URL (for example `https://example.com`). Public, published content syncs without credentials.

To sync private content or authenticate, create an [Application Password](https://wordpress.org/documentation/article/application-passwords/) under **Users > Profile > Application Passwords** and enter your username and that password. Application passwords require WordPress 5.6+ and an HTTPS site.""",
            iconPath="/static/services/wordpress.png",
            docsUrl="https://posthog.com/docs/cdp/sources/wordpress",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="site_url",
                        label="Site URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://example.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="username",
                        label="Username (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="admin",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="application_password",
                        label="Application password (optional)",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=False,
                        placeholder="xxxx xxxx xxxx xxxx xxxx xxxx",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid WordPress username or application password. Create a new application password and reconnect.",
            "403 Client Error": "Your WordPress credentials lack permission to read this data. Check the user's role and try again.",
            HOST_NOT_ALLOWED_ERROR: "The WordPress site URL is not allowed. Please use a publicly reachable site URL.",
            HTTP_NOT_ALLOWED_ERROR: "The WordPress site URL must use HTTPS when credentials are provided. Please update the site URL to use https://.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.wordpress.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: WordpressSourceConfig,
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
        self, config: WordpressSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_wordpress_credentials(config.site_url, config.username, config.application_password, team_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[WordpressResumeConfig]:
        return ResumableSourceManager[WordpressResumeConfig](inputs, WordpressResumeConfig)

    def source_for_pipeline(
        self,
        config: WordpressSourceConfig,
        resumable_source_manager: ResumableSourceManager[WordpressResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return wordpress_source(
            site_url=config.site_url,
            username=config.username,
            application_password=config.application_password,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            team_id=inputs.team_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
