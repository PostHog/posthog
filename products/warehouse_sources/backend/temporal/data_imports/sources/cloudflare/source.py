from typing import Optional, cast

from products.warehouse_sources.backend.facade.codebase_detection import detect
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudflare.cloudflare import (
    DNS_ANALYTICS_ALL_ZONES_FAILED,
    cloudflare_source,
    validate_credentials as validate_cloudflare_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.cloudflare.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, SimpleSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.cloudflare import (
    CloudflareSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class CloudflareSource(SimpleSource[CloudflareSourceConfig]):
    codebase_detection = detect(
        env=(
            "^CLOUDFLARE_",
            "^CF_API_TOKEN$",
            "^CF_ACCOUNT_ID$",
            "^CF_API_KEY$",
            "^CF_EMAIL$",
            "^CF_API_BASE_URL$",
            "^CF_AIG_TOKEN$",
            "^CF_ACCESS_CLIENT_ID$",
            "^CF_ACCESS_CLIENT_SECRET$",
            "^CF_ACCESS_TEAM_DOMAIN$",
            "^CF_ACCESS_AUD$",
            "^WRANGLER_",
            "^MINIFLARE_CACHE_DIR$",
            "^R2_ACCESS_KEY_ID$",
            "^R2_SECRET_ACCESS_KEY$",
            "^TURNSTILE_",
            "^NUXT_PUBLIC_TURNSTILE_SITE_KEY$",
            "^NUXT_TURNSTILE_SECRET_KEY$",
        ),
        script_hosts=(
            "static.cloudflareinsights.com",
            "challenges.cloudflare.com",
            "embed.cloudflarestream.com",
            "iframe.cloudflarestream.com",
            "embed.videodelivery.net",
            "iframe.videodelivery.net",
        ),
        npm=(
            "cloudflare",
            "wrangler",
            "@cloudflare/workers-types",
            "@cloudflare/vite-plugin",
            "@cloudflare/vitest-plugin",
            "@cloudflare/vitest-pool-workers",
            "@cloudflare/kv-asset-handler",
            "@cloudflare/next-on-pages",
            "@opennextjs/cloudflare",
            "@cloudflare/config",
            "@cloudflare/pages-functions",
            "@cloudflare/workers-oauth-provider",
            "@cloudflare/workers-wasi",
            "@cloudflare/workers-honeycomb-logger",
            "@cloudflare/workers-response-store",
            "@cloudflare/wrangler",
            "miniflare",
            "create-cloudflare",
            "cf",
            "@cloudflare/d1",
            "@cloudflare/puppeteer",
            "@cloudflare/playwright",
            "@cloudflare/playwright-mcp",
            "@cloudflare/sandbox",
            "@cloudflare/containers",
            "@cloudflare/actors",
            "@cloudflare/dynamic-workflows",
            "agents",
            "@cloudflare/agents",
            "hono-agents",
            "@cloudflare/ai-chat",
            "@cloudflare/codemode",
            "@cloudflare/think",
            "@cloudflare/voice",
            "@cloudflare/shell",
            "@cloudflare/worker-bundler",
            "@cloudflare/ai",
            "@cloudflare/ai-utils",
            "@cloudflare/ai-gateway",
            "workers-ai-provider",
            "ai-gateway-provider",
            "@cloudflare/tanstack-ai",
            "@cloudflare/ai-search-snippet",
            "@cloudflare/mcp-server-cloudflare",
            "workers-mcp",
            "chanfana",
            "@cloudflare/itty-router-openapi",
            "partyserver",
            "y-partyserver",
            "@cloudflare/stream-react",
            "@cloudflare/stream-angular",
            "@cloudflare/realtimekit",
            "@cloudflare/realtimekit-react",
            "@cloudflare/realtimekit-ui",
            "@cloudflare/realtimekit-react-ui",
            "@cloudflare/realtimekit-angular-ui",
            "@cloudflare/realtimekit-react-native",
            "@cloudflare/realtimekit-react-native-ui",
            "@cloudflare/realtimekit-ui-addons",
            "@cloudflare/realtimekit-recording-sdk",
            "@cloudflare/react-native-webrtc",
            "@cloudflare/turnstile-firebase-app-check",
            "@cloudflare/pages-plugin-turnstile",
            "@cloudflare/pages-plugin-cloudflare-access",
            "@cloudflare/pages-plugin-static-forms",
            "@cloudflare/pages-plugin-vercel-og",
            "@cloudflare/pages-plugin-graphql",
            "@cloudflare/pages-plugin-honeycomb",
            "@cloudflare/pages-plugin-sentry",
            "@cloudflare/pages-plugin-stytch",
            "@cloudflare/pages-plugin-hcaptcha",
            "@cloudflare/pages-plugin-google-chat",
            "@cloudflare/pages-plugin-mailchannels",
            "@marsidev/react-turnstile",
            "react-turnstile",
            "@nuxtjs/turnstile",
            "vue-turnstile",
            "ngx-turnstile",
            "@types/cloudflare-turnstile",
            "turnstile-types",
            "@astrojs/cloudflare",
            "@sveltejs/adapter-cloudflare",
            "@sveltejs/adapter-cloudflare-workers",
            "@remix-run/cloudflare",
            "@remix-run/cloudflare-pages",
            "@remix-run/cloudflare-workers",
            "@react-router/cloudflare",
            "@pulumi/cloudflare",
        ),
        pypi=(
            "cloudflare",
            "python-cloudflare",
            "cloudflare-python",
            "workers-py",
            "workers-runtime-sdk",
            "python-workers-runtime-types",
            "langchain-cloudflare",
            "pulumi-cloudflare",
            "certbot-dns-cloudflare",
        ),
        cargo=("worker", "worker-macros", "worker-build", "cloudflare"),
        composer=("cloudflare/sdk", "cloudflare/cf-ip-rewrite", "cloudflare/cloudflare-magento"),
        go=(
            "github.com/cloudflare/cloudflare-go",
            "github.com/pulumi/pulumi-cloudflare/sdk",
            "github.com/syumai/workers",
        ),
        maven=("com.cloudflare.realtimekit:core", "com.cloudflare.realtimekit:ui-android", "com.pulumi:cloudflare"),
        pub=("realtimekit_core", "realtimekit_ui"),
        rubygems=("cloudflare", "cloudflare-rails"),
        swiftpm=(
            "github.com/cloudflare/realtimekit-ios-core",
            "github.com/cloudflare/realtimekit-ios-ui",
            "github.com/dyte-in/realtimekitui",
        ),
    )

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    supported_versions = ("v4",)
    default_version = "v4"
    api_docs_url = "https://developers.cloudflare.com/api/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CLOUDFLARE

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.cloudflare.com": "Cloudflare authentication failed. Please check your API token.",
            "403 Client Error: Forbidden for url: https://api.cloudflare.com": "Cloudflare denied access. Please check that your API token has read permissions for this resource.",
            DNS_ANALYTICS_ALL_ZONES_FAILED: "Your Cloudflare API token can't read analytics for any of your zones. Add the Zone Analytics read permission to the token, then re-enable the sync.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CLOUDFLARE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Cloudflare",
            caption="""Enter your Cloudflare API token to pull your Cloudflare configuration, security, and usage data into the PostHog Data warehouse.

Create an API token in the [Cloudflare dashboard](https://dash.cloudflare.com/profile/api-tokens) with read permissions for the areas you want to sync, such as Account Settings, Zone, Zone Analytics, DNS, Firewall Services, Logs, Workers, and Access. Zone tables are synced from every zone the token can read, and account tables from every account. Zones and accounts the token can't read are skipped.""",
            iconPath="/static/services/cloudflare.svg",
            docsUrl="https://posthog.com/docs/cdp/sources/cloudflare",
            releaseStatus=ReleaseStatus.GA,
            fields=cast(
                list[FieldType],
                [
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.cloudflare.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: CloudflareSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Most v4 REST lists are small configuration tables with no updated-since
        # filter, so they full refresh. Only endpoints in INCREMENTAL_FIELDS take a
        # server-side timestamp filter.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=endpoint in INCREMENTAL_FIELDS,
                supports_append=endpoint in INCREMENTAL_FIELDS,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self,
        config: CloudflareSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        check = validate_cloudflare_credentials(config.api_token)
        if check.is_valid:
            return True, None

        if check.is_transient:
            return (
                False,
                "Couldn't reach Cloudflare to verify your API token. Try again in a moment.",
            )
        if check.is_malformed:
            return (
                False,
                "Cloudflare couldn't read your API token. Paste an API token, not the Global API Key, "
                "with no extra spaces, then reconnect.",
            )
        # Naming Cloudflare's own reason matters more than naming a remedy: the token is refused
        # for reasons permissions never explain, so guessing one sends people round in circles.
        detail = f" Cloudflare said: {check.reason}." if check.reason else ""
        return (
            False,
            f"Cloudflare rejected your API token.{detail} Check the token is still active, isn't "
            "restricted to IP addresses that exclude PostHog, and hasn't expired, then reconnect.",
        )

    def source_for_pipeline(self, config: CloudflareSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return cloudflare_source(
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
