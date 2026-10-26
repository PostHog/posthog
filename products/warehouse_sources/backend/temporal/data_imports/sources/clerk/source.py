from typing import TYPE_CHECKING, Optional, cast

if TYPE_CHECKING:
    from products.cdp.backend.templates.hog_function_template import HogFunctionTemplateDC

from products.warehouse_sources.backend.facade.codebase_detection import detect
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clerk.clerk import (
    FORBIDDEN_KEY_MESSAGE,
    INSTANCE_NOT_FOUND_MESSAGE,
    ClerkResumeConfig,
    clerk_source,
    validate_credentials as validate_clerk_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.clerk.settings import (
    ENDPOINTS,
    RETIRED_ENDPOINTS,
    WEBHOOK_SCHEMA_NAMES,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    FieldType,
    ResumableSource,
    WebhookCreationResult,
    WebhookDeletionResult,
    WebhookSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.clerk import ClerkSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ClerkSource(
    ResumableSource[ClerkSourceConfig, ClerkResumeConfig],
    WebhookSource[ClerkSourceConfig],
):
    codebase_detection = detect(
        env=(
            "^CLERK_SECRET_KEY$",
            "^NEXT_PUBLIC_CLERK_",
            "^CLERK_PUBLISHABLE_KEY$",
            "^CLERK_WEBHOOK_SIGNING_SECRET$",
            "^CLERK_ENCRYPTION_KEY$",
            "^VITE_CLERK_",
            "^EXPO_PUBLIC_CLERK_PUBLISHABLE_KEY$",
            "^PUBLIC_CLERK_PUBLISHABLE_KEY$",
            "^PUBLIC_CLERK_",
            "^NUXT_PUBLIC_CLERK_",
            "^NUXT_CLERK_",
            "^EXPO_PUBLIC_CLERK_",
            "^PLASMO_PUBLIC_CLERK_",
            "^REACT_APP_CLERK_",
            "^GATSBY_CLERK_",
            "^PUBLIC_ASTRO_APP_CLERK_",
            "^CLERK_JWT_KEY$",
            "^CLERK_PEM_PUBLIC_KEY$",
            "^CLERK_MACHINE_SECRET_KEY$",
            "^CLERK_API_KEY$",
            "^CLERK_PLATFORM_API_KEY$",
            "^CLERK_API_(URL|VERSION|BASE)$",
            "^CLERK_FRONTEND_API(_URL)?$",
            "^CLERK_JS_(URL|VERSION)$",
            "^CLERK_(DOMAIN|PROXY_URL|IS_SATELLITE)$",
            "^CLERK_SIGN_(IN|UP|OUT)_URL$",
            "^CLERK_SIGN_(IN|UP)_(FALLBACK|FORCE)_REDIRECT_URL$",
            "^CLERK_AFTER_SIGN_(IN|UP)_URL$",
            "^CLERK_USER_PROFILE_URL$",
            "^CLERK_TELEMETRY_(DISABLED|DEBUG)$",
            "^CLERK_TESTING_TOKEN$",
            "^CLERK_KEYLESS_DISABLED$",
            "^CLERK_SKIP_RAILTIE$",
        ),
        script_hosts=("clerk.accounts.dev", "lcl.dev"),
        npm=(
            "@clerk/nextjs",
            "@clerk/clerk-react",
            "@clerk/backend",
            "@clerk/express",
            "@clerk/fastify",
            "@clerk/remix",
            "@clerk/react",
            "@clerk/clerk-js",
            "@clerk/astro",
            "@clerk/vue",
            "@clerk/nuxt",
            "@clerk/react-router",
            "@clerk/tanstack-react-start",
            "@clerk/expo",
            "@clerk/clerk-expo",
            "@clerk/chrome-extension",
            "@clerk/clerk-sdk-node",
            "clerk",
            "@clerk/hono",
            "@clerk/electron",
            "@clerk/electron-passkeys",
            "@clerk/expo-passkeys",
            "@clerk/expo-biometrics",
            "@clerk/expo-google-signin",
            "@clerk/expo-native-components",
            "@clerk/ui",
            "@clerk/shared",
            "@clerk/types",
            "@clerk/themes",
            "@clerk/localizations",
            "@clerk/elements",
            "@clerk/mosaic",
            "@clerk/testing",
            "@clerk/eslint-plugin",
            "@clerk/mcp-tools",
            "@clerk/agent-toolkit",
            "@clerk/tanstack-start",
            "@clerk/edge",
            "@clerk/backend-core",
            "gatsby-plugin-clerk",
            "ngx-clerk",
            "elysia-clerk",
            "@hono/clerk-auth",
            "@dimkl/clerk-koa",
            "clerk-solidjs",
            "svelte-clerk",
            "clerk-sveltekit",
            "vue-clerk",
            "astro-clerk-auth",
            "tauri-plugin-clerk",
            "@redwoodjs/auth-clerk-web",
            "@redwoodjs/auth-clerk-api",
        ),
        pypi=("clerk-backend-api", "fastapi-clerk-auth"),
        cargo=("clerk-rs", "tauri-plugin-clerk"),
        composer=("clerkinc/backend-php",),
        go=("github.com/clerk/clerk-sdk-go",),
        hex=("clerk",),
        maven=(
            "com.clerk:backend-api",
            "com.clerk:backend-api-spring-boot-starter",
            "com.clerk:backend-api-spring-boot-autoconfigure",
            "com.clerk:clerk-android",
            "com.clerk:clerk-android-api",
            "com.clerk:clerk-android-ui",
            "com.clerk:clerk-convex-kotlin",
        ),
        pub=("clerk_flutter", "clerk_auth", "clerk_backend_api"),
        rubygems=("clerk-sdk-ruby", "clerk-http-client", "clerk-rails"),
        swiftpm=("github.com/clerk/clerk-ios", "github.com/clerk/clerk-convex-swift"),
    )

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://clerk.com/docs/reference/backend-api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CLERK

    @property
    def webhook_template(self) -> Optional["HogFunctionTemplateDC"]:
        from products.warehouse_sources.backend.temporal.data_imports.sources.clerk.webhook_template import template

        return template

    @property
    def webhook_resource_map(self) -> dict[str, str]:
        return {name: name for name in WEBHOOK_SCHEMA_NAMES}

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CLERK,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Clerk",
            releaseStatus=ReleaseStatus.GA,
            caption="""Enter your Clerk secret key to automatically pull your Clerk data into the PostHog Data warehouse.

You can find your secret key in your [Clerk Dashboard](https://dashboard.clerk.com/) under **API Keys**.

The secret key starts with `sk_live_`.
""",
            iconPath="/static/services/clerk.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="secret_key",
                        label="Secret key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="sk_live_...",
                        secret=True,
                    ),
                ],
            ),
            webhookManualOnly=True,
            webhookSetupCaption="""Webhook sync keeps the users, organizations, and organization memberships tables up to date. Set it up in Clerk:

1. In the [Clerk Dashboard](https://dashboard.clerk.com/), go to **Configure** > **Webhooks** and select **Add Endpoint**.
2. Paste the webhook URL shown below into **Endpoint URL**.
3. Subscribe to the `user`, `organization`, and `organizationMembership` created and updated events.
4. Open the endpoint, copy its **Signing Secret**, and paste it into the field below.

Clerk delete events only carry the record ID, so webhook sync doesn't remove deleted records. Resync a table to remove them.
""",
            webhookFields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="signing_secret",
                        label="Signing secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="whsec_...",
                        secret=True,
                    )
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.clerk.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: ClerkSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # The Clerk API can't filter by updated_at, so a polled sync is always a full refresh. The
        # tables in WEBHOOK_SCHEMA_NAMES can switch to webhook sync after the initial backfill.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                supports_webhooks=endpoint in WEBHOOK_SCHEMA_NAMES,
                incremental_fields=[],
            )
            for endpoint in list(ENDPOINTS)
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.clerk.com": "Your Clerk secret key is invalid or has been revoked. Please update the secret key in your Clerk dashboard and reconnect.",
            # Listed before the host-wide 403 below, since the first matching key supplies the message.
            "403 Client Error: Forbidden for url: https://api.clerk.com/v1/users": FORBIDDEN_KEY_MESSAGE,
            # Clerk secret keys carry no per-key permissions, so a 403 on any other table usually means
            # the table's feature is off for the instance. Pointing the customer at key permissions dead-ends.
            "403 Client Error: Forbidden for url: https://api.clerk.com": (
                "Clerk denied access to this table. Check that the feature it needs is turned on for "
                "your Clerk instance, or turn off syncing for this table."
            ),
            # Clerk answers 410 for endpoints it has removed. Schema discovery retires the table
            # within a few hours, so this only covers runs that start in between.
            "410 Client Error: Gone for url: https://api.clerk.com": "Clerk removed this endpoint from its API, so this table can't sync any more. Turn off syncing for this table.",
            # Clerk's own API spec documents only 402/403/422 as possible error responses for this
            # (deprecated) list endpoint — no successful, well-formed request should ever hit this,
            # so a 422 here means SAML connections (Enterprise SSO) aren't available on this Clerk
            # instance. Scoped to this path, not all of api.clerk.com, since 422 elsewhere can mean
            # a genuinely bad request that's worth investigating rather than an account limitation.
            "422 Client Error: Unprocessable Entity for url: https://api.clerk.com/v1/saml_connections": "SAML connections (Enterprise SSO) aren't available on your Clerk plan or instance. Turn off syncing for this table, or enable SAML connections in your Clerk dashboard.",
            # Clerk answers 422 feature_requires_email_address_enabled for enterprise_connections when
            # Enterprise SSO isn't available on the instance. The unfiltered list request is identical
            # every run, so it re-fails on every schedule; classify it so the schema pauses instead of
            # retrying. Scoped to this path, mirroring saml_connections, since a 422 elsewhere can be a
            # genuinely bad request worth investigating rather than an account limitation.
            "422 Client Error: Unprocessable Entity for url: https://api.clerk.com/v1/enterprise_connections": "Enterprise SSO connections aren't available on your Clerk plan or instance. Turn off syncing for this table, or enable Enterprise SSO in your Clerk dashboard.",
            # Clerk's list api_keys endpoint requires a subject (a user or organization id), so the
            # unfiltered list request we send is rejected with a 400 every run. Scoped to this path,
            # not all of api.clerk.com, since a 400 elsewhere can be a genuinely bad request worth
            # investigating rather than an endpoint that can't be listed.
            "400 Client Error: Bad Request for url: https://api.clerk.com/v1/api_keys": "The API keys table can't be synced from Clerk. Turn off syncing for this table.",
            # Clerk answers 404 resource_not_found for redirect_urls on instances/plans where the
            # resource isn't available. The request is identical every run, so it re-fails on every
            # schedule; classify it so the schema is paused instead of burning a job each time. Scoped
            # to this path, not all of api.clerk.com, since a 404 elsewhere can be a genuinely missing
            # record worth investigating rather than an account limitation.
            "404 Client Error: Not Found for url: https://api.clerk.com/v1/redirect_urls": "The redirect URLs table isn't available on your Clerk plan or instance. Turn off syncing for this table.",
            # Clerk answers the same 404 resource_not_found for jwt_templates on instances/plans
            # that don't serve the resource. An instance that does serve it returns 200 with an
            # empty array when no template exists, so the 404 can't mean "none configured". The
            # unfiltered list request is identical every run, so it re-fails on every schedule.
            # Scoped to this path for the same reason as redirect_urls above.
            "404 Client Error: Not Found for url: https://api.clerk.com/v1/jwt_templates": "The JWT templates table isn't available on your Clerk plan or instance. Turn off syncing for this table.",
            # The users list exists on every Clerk instance, and an instance with no users answers
            # 200 with an empty array, so a 404 resource_not_found here can't mean a missing record
            # — Clerk won't resolve the instance the key belongs to at all. The request is identical
            # every run, so it re-fails on every schedule. Scoped to this path, like the two
            # entries above; `users` is also the parent of the sessions fan-out, so the copy names
            # the key rather than one table.
            "404 Client Error: Not Found for url: https://api.clerk.com/v1/users": INSTANCE_NOT_FOUND_MESSAGE,
            **{reason: reason for reason in RETIRED_ENDPOINTS.values()},
        }

    def validate_credentials(
        self, config: ClerkSourceConfig, team_id: int, schema_name: Optional[str] = None, api_version: str | None = None
    ) -> tuple[bool, str | None]:
        return validate_clerk_credentials(config.secret_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ClerkResumeConfig]:
        return ResumableSourceManager[ClerkResumeConfig](inputs, ClerkResumeConfig)

    def get_webhook_source_manager(self, inputs: SourceInputs) -> WebhookSourceManager:
        return WebhookSourceManager(inputs, inputs.logger)

    def create_webhook(
        self, config: ClerkSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> WebhookCreationResult:
        return WebhookCreationResult(
            success=False,
            error="Clerk does not support automatic webhook creation. Please follow the manual setup instructions.",
        )

    def delete_webhook(
        self, config: ClerkSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> WebhookDeletionResult:
        # PostHog never creates the Clerk endpoint, so there is nothing to remove on Clerk's side.
        return WebhookDeletionResult(success=True)

    def source_for_pipeline(
        self,
        config: ClerkSourceConfig,
        resumable_source_manager: ResumableSourceManager[ClerkResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return clerk_source(
            secret_key=config.secret_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            logger=inputs.logger,
            webhook_source_manager=self.get_webhook_source_manager(inputs),
        )
