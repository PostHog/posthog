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
    WORDPRESS_COM_AUTH_REQUIRED_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.wordpress.wordpress import (
    HOST_NOT_ALLOWED_ERROR,
    HTTP_NOT_ALLOWED_ERROR,
    WPCOM_AUTH_REQUIRED_TABLE_ERROR,
    WPCOM_PRIVATE_SITE_ERROR,
    WordpressResumeConfig,
    uses_wordpress_com_proxy,
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
            caption="""Sync posts, pages, comments, media, categories, tags, and users from a WordPress site via the WordPress REST API.

**Self-hosted sites and WordPress.com Business/Commerce plans:** enter the site URL (for WordPress.com Business/Commerce, use your custom domain). Public, published content syncs without credentials. To sync protected content, create an [Application Password](https://wordpress.org/documentation/article/application-passwords/) under **Users > Profile > Application Passwords** (requires WordPress 5.6+ and HTTPS) and enter your username and that password.

**Free, Personal, and Premium WordPress.com sites:** the site must be launched and public. Content syncs anonymously through the WordPress.com public API, so leave username and password empty. The media and users tables are not available on these plans, and private WordPress.com sites are not supported.""",
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
                        caption="For example https://example.com, or yoursite.wordpress.com for WordPress.com sites",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="username",
                        label="Username (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="admin",
                        caption="Self-hosted and WordPress.com Business sites only. Leave empty for free WordPress.com sites",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="application_password",
                        label="Application password (optional)",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=False,
                        placeholder="xxxx xxxx xxxx xxxx xxxx xxxx",
                        caption="Created under Users > Profile > Application Passwords. Leave empty for free WordPress.com sites",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid WordPress username or application password. Create a new application password and reconnect.",
            "403 Client Error": "WordPress denied access to this data (HTTP 403). If you provided credentials, check the user's role; otherwise a security plugin, firewall, or the site's privacy settings may be blocking REST API access.",
            "404 Client Error": "WordPress returned 404 (Not Found) for this collection. The REST API or this specific endpoint (for example /users, which security plugins often block to prevent user enumeration) may be disabled or restricted on your site. Enable REST API access for it, or remove this table from the sync.",
            WPCOM_PRIVATE_SITE_ERROR: "This WordPress.com site is private or not yet launched. Launch the site and set its privacy to Public, then sync again.",
            WPCOM_AUTH_REQUIRED_TABLE_ERROR: "Free WordPress.com sites only expose public content, so the media and users tables are not available for this site. Remove them from the sync.",
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
        endpoints: tuple[str, ...] = ENDPOINTS
        if uses_wordpress_com_proxy(config.site_url):
            # The wp.com proxy only serves media/users with OAuth; hide them so the wizard doesn't
            # offer tables that can never sync.
            endpoints = tuple(e for e in ENDPOINTS if e not in WORDPRESS_COM_AUTH_REQUIRED_ENDPOINTS)
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=bool(INCREMENTAL_FIELDS.get(endpoint)),
                supports_append=bool(INCREMENTAL_FIELDS.get(endpoint)),
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in endpoints
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
