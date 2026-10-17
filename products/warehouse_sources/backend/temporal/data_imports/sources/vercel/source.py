from typing import Optional, cast

from products.warehouse_sources.backend.facade.codebase_detection import detect
from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.vercel import VercelSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.vercel.settings import VERCEL_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.vercel.vercel import (
    VercelResumeConfig,
    validate_credentials as validate_vercel_credentials,
    vercel_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class VercelSource(ResumableSource[VercelSourceConfig, VercelResumeConfig]):
    codebase_detection = detect(
        env=(
            "^VERCEL_API_TOKEN$",
            "^VERCEL_TOKEN$",
            "^VERCEL_ORG_ID$",
            "^VERCEL$",
            "^VERCEL_PROJECT_ID$",
            "^VERCEL_TEAM_ID$",
            "^VERCEL_OIDC_TOKEN$",
            "^VERCEL_AUTOMATION_BYPASS_SECRET$",
            "^VERCEL_URL$",
            "^VERCEL_ENV$",
            "^VERCEL_TARGET_ENV$",
            "^VERCEL_BRANCH_URL$",
            "^VERCEL_PROJECT_PRODUCTION_URL$",
            "^VERCEL_GIT_COMMIT_SHA$",
            "^VERCEL_GIT_COMMIT_REF$",
            "^VERCEL_GIT_PROVIDER$",
            "^VERCEL_GIT_REPO_SLUG$",
            "^VERCEL_GIT_REPO_OWNER$",
            "^NEXT_PUBLIC_VERCEL_URL$",
            "^NEXT_PUBLIC_VERCEL_ENV$",
            "^VITE_VERCEL_URL$",
            "^VITE_VERCEL_ENV$",
            "^PUBLIC_VERCEL_URL$",
            "^PUBLIC_VERCEL_ENV$",
            "^REACT_APP_VERCEL_URL$",
            "^REACT_APP_VERCEL_ENV$",
            "^GATSBY_VERCEL_URL$",
            "^GATSBY_VERCEL_ENV$",
            "^NUXT_ENV_VERCEL_URL$",
            "^NUXT_ENV_VERCEL_ENV$",
            "^BLOB_READ_WRITE_TOKEN$",
            "^BLOB_STORE_ID$",
            "^BLOB_WEBHOOK_PUBLIC_KEY$",
            "^EDGE_CONFIG$",
            "^KV_REST_API_URL$",
            "^KV_REST_API_TOKEN$",
            "^KV_REST_API_READ_ONLY_TOKEN$",
            "^KV_URL$",
            "^FLAGS_SECRET$",
            "^AI_GATEWAY_API_KEY$",
        ),
        script_hosts=("va.vercel-scripts.com", "cdn.vercel-insights.com", "vercel.live"),
        npm=(
            "@vercel/sdk",
            "vercel",
            "@vercel/analytics",
            "@vercel/speed-insights",
            "@vercel/blob",
            "@vercel/edge-config",
            "@vercel/global-config",
            "@vercel/kv",
            "@vercel/postgres",
            "@vercel/postgres-kysely",
            "@vercel/functions",
            "@vercel/edge",
            "@vercel/og",
            "@vercel/otel",
            "@vercel/firewall",
            "@vercel/flags",
            "@vercel/flags-core",
            "@flags-sdk/vercel",
            "@vercel/toolbar",
            "@vercel/sandbox",
            "@vercel/queue",
            "@vercel/oidc",
            "@vercel/oidc-aws-credentials-provider",
            "@vercel/kms",
            "@vercel/passport",
            "@vercel/connect",
            "@vercel/config",
            "@vercel/microfrontends",
            "@vercel/related-projects",
            "@vercel/remix",
            "@vercel/react-router",
            "@vercel/client",
            "@vercel/node",
            "@vercel/remote",
            "@vercel/remote-nx",
            "@vercel/remote-rush",
            "@vercel/slack-bolt",
            "@vercel/gatsby-plugin-vercel-analytics",
            "@vercel/gatsby-plugin-vercel-builder",
            "@vercel/aws",
            "@workflow/world-vercel",
            "gatsby-plugin-vercel",
            "@sveltejs/adapter-vercel",
            "@astrojs/vercel",
            "@remix-run/vercel",
            "@hono/vercel",
            "vite-plugin-vercel",
            "@docusaurus/plugin-vercel-analytics",
        ),
        pypi=(
            "vercel",
            "vercel-sdk",
            "vercel-oidc",
            "vercel-sandbox",
            "vercel-workflow",
            "vercel-queue",
            "vercel-cache",
            "vercel-headers",
            "vercel-connect",
            "vercel-workers",
            "vercel-celery",
            "vercel-dramatiq",
            "vercel-apscheduler",
            "vercel-blob",
        ),
        cargo=("vercel_runtime", "vercel_axum"),
    )

    api_docs_url = "https://vercel.com/docs/rest-api"
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.VERCEL

    @property
    def connection_host_fields(self) -> list[str]:
        # `team_id` selects which Vercel team the stored access token is used against. Editing it
        # on an existing source must force the token to be re-entered — otherwise an editor could
        # retarget the preserved token at another Vercel team it can access.
        return ["team_id"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.VERCEL,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Vercel",
            releaseStatus=ReleaseStatus.GA,
            caption="""Enter a Vercel access token to pull your Vercel deployments, deployment check runs, projects, teams, domains, aliases, and billing usage into the PostHog Data warehouse.

Create an access token in your [Vercel account settings](https://vercel.com/account/tokens). A read-only token is sufficient.

To sync resources owned by a team, also enter the team's ID (found under **Team Settings**). Leave it blank to sync resources owned by the token's user. Syncing the **billing_charges** table needs a token whose role can read billing (Owner, Member, Developer, Security, Billing, or Enterprise Viewer).""",
            iconPath="/static/services/vercel.png",
            docsUrl="https://posthog.com/docs/cdp/sources/vercel",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="team_id",
                        label="Team ID (optional)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="team_...",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.vercel.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # 401/403 surface as a requests HTTPError when `_fetch_page` calls raise_for_status().
            # Retrying never satisfies a credential/permission problem, so stop the sync. Match the
            # stable status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.vercel.com": "Your Vercel access token is invalid or has been revoked. Create a new token in your Vercel account settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.vercel.com": "Your Vercel access token is not authorized for this resource. Check the token's scope (and team access), then reconnect.",
            # Vercel's FOCUS billing endpoint 404s when the configured team can't be resolved for
            # this token (wrong/missing Team ID, or the token's user no longer belongs to that
            # team) rather than the 403 it returns for a role that lacks billing access. Retrying
            # never resolves a bad team reference, so stop the sync. Match the stable path, not the
            # query string (it carries the per-request date window and team id).
            "404 Client Error: Not Found for url: https://api.vercel.com/v1/billing/charges": "Vercel couldn't find billing data for the configured team. Check that the Team ID is correct and that your access token's user still belongs to that team, then reconnect.",
        }

    def get_retryable_errors(self) -> set[str]:
        # `_fetch_page`/`_open_billing_stream` already retry these in-process (a 429/5xx surfaces as
        # the "Vercel API error (retryable)" sentinel; connection failures and read timeouts surface
        # as the urllib3 pool error). Once those retries exhaust, Temporal retries the whole activity
        # and the failure is transient and self-recovering, so don't surface it as tracked exception
        # noise. The host is a constant, not user input, so matching on it doesn't risk swallowing an
        # unrelated failure.
        return {
            "Vercel API error (retryable)",
            "HTTPSConnectionPool(host='api.vercel.com', port=443)",
        }

    def get_schemas(
        self,
        config: VercelSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=name,
                supports_incremental=endpoint_config.supports_incremental,
                supports_append=endpoint_config.supports_append,
                incremental_fields=endpoint_config.incremental_fields,
                default_incremental_lookback_seconds=endpoint_config.default_incremental_lookback_seconds,
            )
            for name, endpoint_config in VERCEL_ENDPOINTS.items()
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: VercelSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_vercel_credentials(config.access_token)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[VercelResumeConfig]:
        return ResumableSourceManager[VercelResumeConfig](inputs, VercelResumeConfig)

    def source_for_pipeline(
        self,
        config: VercelSourceConfig,
        resumable_source_manager: ResumableSourceManager[VercelResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return vercel_source(
            access_token=config.access_token,
            endpoint=inputs.schema_name,
            team_id=config.team_id,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
