from typing import Optional, cast

from posthog.schema_enums import ProductKey

from products.warehouse_sources.backend.facade.codebase_detection import detect
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bugsnag.bugsnag import (
    BugsnagResumeConfig,
    bugsnag_source,
    validate_credentials as validate_bugsnag_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.bugsnag.settings import (
    BUGSNAG_ENDPOINTS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.bugsnag import (
    BugsnagSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BugsnagSource(ResumableSource[BugsnagSourceConfig, BugsnagResumeConfig]):
    codebase_detection = detect(
        env=("^BUGSNAG_", "^NEXT_PUBLIC_BUGSNAG_API_KEY$", "^GATSBY_BUGSNAG_API_KEY$"),
        script_hosts=("d2wy8f7a9ursnm.cloudfront.net",),
        npm=(
            "@bugsnag/js",
            "@bugsnag/browser",
            "@bugsnag/node",
            "@bugsnag/react-native",
            "@bugsnag/expo",
            "@bugsnag/plugin-react",
            "@bugsnag/plugin-vue",
            "@bugsnag/plugin-angular",
            "@bugsnag/plugin-express",
            "@bugsnag/plugin-koa",
            "@bugsnag/plugin-restify",
            "@bugsnag/plugin-hono",
            "@bugsnag/plugin-aws-lambda",
            "@bugsnag/plugin-cloudflare-workers",
            "@bugsnag/plugin-react-navigation",
            "@bugsnag/plugin-react-native-navigation",
            "@bugsnag/plugin-expo-eas-sourcemaps",
            "@bugsnag/web-worker",
            "@bugsnag/electron",
            "@bugsnag/vega",
            "@bugsnag/vega-native",
            "@bugsnag/vega-plugin-react-navigation",
            "@bugsnag/react-native-cli",
            "@bugsnag/cli",
            "@bugsnag/source-maps",
            "@bugsnag/vite-plugin-bugsnag",
            "@bugsnag/browser-performance",
            "@bugsnag/js-performance",
            "@bugsnag/react-native-performance",
            "@bugsnag/expo-performance",
            "@bugsnag/angular-performance",
            "@bugsnag/react-router-performance",
            "@bugsnag/vue-router-performance",
            "@bugsnag/svelte-kit-performance",
            "@bugsnag/plugin-react-performance",
            "@bugsnag/plugin-react-navigation-performance",
            "@bugsnag/plugin-react-native-navigation-performance",
            "@bugsnag/plugin-named-spans",
            "@bugsnag/plugin-react-native-span-access",
            "webpack-bugsnag-plugins",
            "bugsnag-expo-cli",
            "bugsnag-build-reporter",
            "bugsnag",
            "bugsnag-js",
            "bugsnag-react-native",
            "bugsnag-sourcemaps",
            "bugsnag-react",
            "bugsnag-vue",
            "bugsnag-angular",
            "grunt-bugsnag",
            "gulp-bugsnag",
        ),
        pypi=("bugsnag",),
        cocoapods=(
            "Bugsnag",
            "BugsnagNetworkRequestPlugin",
            "BugsnagPerformance",
            "BugsnagPerformanceSwift",
            "BugsnagPerformanceSwiftUI",
            "BugsnagPerformanceNamedSpans",
        ),
        composer=(
            "bugsnag/bugsnag",
            "bugsnag/bugsnag-laravel",
            "bugsnag/bugsnag-symfony",
            "bugsnag/bugsnag-psr-logger",
            "bugsnag/bugsnag-silex",
            "bugsnag/bugsnag-wordpress",
        ),
        go=(
            "github.com/bugsnag/bugsnag-go",
            "github.com/bugsnag/bugsnag-go-gin",
            "github.com/bugsnag/bugsnag-go-negroni",
            "github.com/bugsnag/bugsnag-go-revel",
            "github.com/bugsnag/bugsnag-go-performance",
        ),
        hex=("bugsnag",),
        maven=(
            "com.bugsnag:bugsnag-android",
            "com.bugsnag:bugsnag",
            "com.bugsnag:bugsnag-android-core",
            "com.bugsnag:bugsnag-android-ndk",
            "com.bugsnag:bugsnag-plugin-android-anr",
            "com.bugsnag:bugsnag-plugin-android-apphang",
            "com.bugsnag:bugsnag-plugin-android-exitinfo",
            "com.bugsnag:bugsnag-plugin-android-ndk",
            "com.bugsnag:bugsnag-plugin-android-okhttp",
            "com.bugsnag:bugsnag-android-performance",
            "com.bugsnag:bugsnag-android-performance-appcompat",
            "com.bugsnag:bugsnag-android-performance-compose",
            "com.bugsnag:bugsnag-android-performance-coroutines",
            "com.bugsnag:bugsnag-android-performance-okhttp",
            "com.bugsnag:bugsnag-plugin-android-performance-named-spans",
            "com.bugsnag:bugsnag-android-gradle-plugin",
            "com.bugsnag:bugsnag-gradle-plugin",
            "com.bugsnag.gradle:com.bugsnag.gradle.gradle.plugin",
            "com.bugsnag:bugsnag-kmp",
            "com.bugsnag:bugsnag-spring",
        ),
        pub=(
            "bugsnag_flutter",
            "bugsnag_flutter_performance",
            "bugsnag_http_client",
            "bugsnag_flutter_dart_io_http_client",
            "bugsnag_breadcrumbs_http",
            "bugsnag_breadcrumbs_dart_io",
            "bugsnag_bridge",
        ),
        rubygems=(
            "bugsnag",
            "bugsnag_performance",
            "bugsnag-api",
            "bugsnag-capistrano",
            "fastlane-plugin-bugsnag",
            "cocoapods-bugsnag",
            "bugsnag-em",
        ),
        swiftpm=("github.com/bugsnag/bugsnag-cocoa", "github.com/bugsnag/bugsnag-cocoa-performance"),
        alternative_to=(ProductKey.ERROR_TRACKING,),
    )

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    supported_versions = ("2",)  # Data Access API X-Version header value
    default_version = "2"
    api_docs_url = "https://developer.smartbear.com/bugsnag/docs/data-access"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BUGSNAG

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.BUGSNAG,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Bugsnag",
            releaseStatus=ReleaseStatus.GA,
            caption="""Enter your BugSnag personal auth token to pull your BugSnag error-monitoring data into the PostHog Data warehouse.

You can generate a personal auth token in the **My Account** section of your [BugSnag account settings](https://app.bugsnag.com/settings/my-account/). The token inherits your account's access, so it can read every organization and project you can see.""",
            iconPath="/static/services/bugsnag.png",
            docsUrl="https://posthog.com/docs/cdp/sources/bugsnag",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="auth_token",
                        label="Auth token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Personal auth token",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # 401/403 surface as a requests HTTPError when `_fetch_page` calls `raise_for_status()`.
        # No amount of retrying fixes a bad or under-permissioned token, so stop the sync. Match the
        # stable status text and base host, not the per-request path/query.
        return {
            "401 Client Error: Unauthorized for url: https://api.bugsnag.com": "Your BugSnag auth token is invalid or has been revoked. Generate a new personal auth token in your BugSnag account settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.bugsnag.com": "Your BugSnag auth token does not have access to this data. Check the token's account permissions, then reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.bugsnag.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: BugsnagSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        def _description(endpoint: str) -> str | None:
            if endpoint == "events":
                return "One row per captured event. Can be very large — full refresh only, off by default."
            if endpoint == "pivot_values":
                return "One row per value of each pivot. As wide as the underlying event field — off by default."
            if endpoint == "error_trend":
                return (
                    "Event counts over time for each error, in 12-hour buckets. Covers each project's 25 most "
                    "recently seen errors. Off by default because it makes one request per error."
                )
            if endpoint == "error_pivot_values":
                return (
                    "One row per pivot value for each error. Covers each project's 10 most recently seen "
                    "errors. Off by default because it makes one request for every error and pivot."
                )
            if endpoint == "span_group_spans":
                return (
                    "Individual spans under each span group. BugSnag serves only the most recent page per "
                    "group, so this is a sample of recent spans rather than the full history. Off by default."
                )
            return None

        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = BUGSNAG_ENDPOINTS[endpoint]
            # Full refresh only: BugSnag exposes dashboard-style time filters on errors/events/releases,
            # but the filter+pagination behavior isn't verified against the live API yet, so we don't
            # advertise incremental rather than risk a sync that silently re-walks history.
            return SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
                description=_description(endpoint),
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: BugsnagSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_bugsnag_credentials(config.auth_token)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[BugsnagResumeConfig]:
        return ResumableSourceManager[BugsnagResumeConfig](inputs, BugsnagResumeConfig)

    def source_for_pipeline(
        self,
        config: BugsnagSourceConfig,
        resumable_source_manager: ResumableSourceManager[BugsnagResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return bugsnag_source(
            auth_token=config.auth_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
