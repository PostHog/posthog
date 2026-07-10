import secrets
from typing import TYPE_CHECKING, Optional, cast

if TYPE_CHECKING:
    from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthConfig,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)

from posthog.models.integration import GitHubIntegration

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import (
    ExternalWebhookInfo,
    FieldType,
    ResumableSource,
    WebhookCreationResult,
    WebhookDeletionResult,
    WebhookSource,
    WebhookSyncResult,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import OAuthMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GithubSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.github.github import (
    ORG_SCOPED_ENDPOINTS,
    GithubEgressIdentity,
    GithubResumeConfig,
    check_org_endpoint_permission,
    create_repo_webhook,
    delete_repo_webhook,
    get_repo_webhook_info,
    github_source,
    update_repo_webhook,
    validate_credentials as validate_github_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.github.settings import (
    ENDPOINTS,
    GITHUB_ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

# Schemas that can be fed by GitHub webhooks, mapped to the X-GitHub-Event header
# value the webhook handler routes on (schema_mapping is keyed by these values).
GITHUB_WEBHOOK_RESOURCE_MAP: dict[str, str] = {
    "workflow_jobs": "workflow_job",
    "workflow_runs": "workflow_run",
    "reviews": "pull_request_review",
}


@SourceRegistry.register
class GithubSource(
    ResumableSource[GithubSourceConfig, GithubResumeConfig],
    WebhookSource[GithubSourceConfig],
    OAuthMixin,
):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GITHUB

    @property
    def webhook_template(self) -> Optional["HogFunctionTemplateDC"]:
        from products.warehouse_sources.backend.temporal.data_imports.sources.github.webhook_template import template

        return template

    @property
    def webhook_resource_map(self) -> dict[str, str]:
        return GITHUB_WEBHOOK_RESOURCE_MAP

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GITHUB,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            featured=True,
            label="GitHub",
            releaseStatus=ReleaseStatus.GA,
            caption="Connect your GitHub repository to sync issues, pull requests, commits, and more.",
            iconPath="/static/services/github.png",
            iconClassName="dark:bg-white rounded",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="auth_method",
                        label="Authentication type",
                        required=True,
                        defaultValue="oauth",
                        options=[
                            SourceFieldSelectConfigOption(
                                label="OAuth (GitHub App)",
                                value="oauth",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldOauthConfig(
                                            name="github_integration_id",
                                            label="GitHub account",
                                            required=False,
                                            kind="github",
                                        ),
                                    ],
                                ),
                            ),
                            SourceFieldSelectConfigOption(
                                label="Personal access token",
                                value="pat",
                                fields=cast(
                                    list[FieldType],
                                    [
                                        SourceFieldInputConfig(
                                            name="personal_access_token",
                                            label="Personal access token",
                                            type=SourceFieldInputConfigType.PASSWORD,
                                            required=False,
                                            placeholder="github_pat_...",
                                            caption="You can create a personal access token in your [GitHub Settings](https://github.com/settings/tokens) under **Developer settings > Personal access tokens**.",
                                            secret=True,
                                        ),
                                    ],
                                ),
                            ),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="repository",
                        label="Repository",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="owner/repo",
                        secret=False,
                    ),
                ],
            ),
            webhookSetupCaption="""To set up the webhook manually:

1. Go to your repository's **Settings > Webhooks** on GitHub
2. Click **Add webhook**
3. Paste the webhook URL shown below into the **Payload URL** field
4. Set **Content type** to **application/json**
5. Enter a **Secret** and add the same value to the **Signing secret** field below
6. Under **Which events would you like to trigger this webhook?**, choose **Let me select individual events** and tick **Workflow jobs**, **Workflow runs**, and **Pull request reviews**
7. Click **Add webhook**

If automatic creation failed, your token needs webhook permissions — the **admin:repo_hook** scope on a classic token, or **Repository webhooks: read and write** on a fine-grained token. Add it and reconnect, or set the webhook up manually using the steps above.""",
            webhookFields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="signing_secret",
                        label="Signing secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="your webhook secret",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.github.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid GitHub credentials. Please reconnect your account.",
            "403 Client Error": "Access forbidden. Your token may lack required permissions or have hit rate limits.",
            "404 Client Error": "Repository not found. Please verify the repository name and access permissions.",
            "Bad credentials": "Your GitHub connection is invalid or expired. Please reconnect.",
            # The GitHub App isn't configured on this PostHog instance, so an OAuth source can't mint
            # the App JWT to refresh its installation token. Deterministic — retrying never resolves it.
            "GITHUB_APP_CLIENT_ID is not configured": "The GitHub App is not configured on this PostHog instance. Please contact support.",
            "GITHUB_APP_PRIVATE_KEY is not configured": "The GitHub App is not configured on this PostHog instance. Please contact support.",
            # A 404 from POST /app/installations/{id}/access_tokens means the GitHub App installation
            # no longer exists (uninstalled or its access revoked). Retrying can never mint a token, so
            # stop syncing until the user reconnects. Match the not-found body specifically — a bare
            # "Failed to refresh installation token" prefix would also swallow transient 5xx/429
            # refresh failures, which must stay retryable.
            'Failed to refresh installation token: {"message":"Not Found"': "Your GitHub App installation could not be found. It may have been uninstalled or had its access revoked. Please reconnect your GitHub account.",
            # GitHub suspends an App installation (org owner action, or GitHub itself) and returns
            # a 403 "This installation has been suspended" when minting a token. The custom
            # GitHubIntegrationError message isn't a requests "403 Client Error" string, so it
            # falls through the status-text keys above. Retrying can't unsuspend it.
            "This installation has been suspended": "Your GitHub App installation has been suspended. Re-enable it from your GitHub organization's installed GitHub Apps settings, then reconnect your GitHub account.",
            # Deterministic credential/config errors from _get_access_token and OAuthMixin.
            # These never resolve on retry — the source needs reconfiguring or reconnecting.
            "Missing GitHub integration ID": "No GitHub account is connected. Please reconnect your GitHub account.",
            "Missing personal access token": "GitHub personal access token is not configured. Please update the source configuration.",
            "GitHub access token not found": "GitHub OAuth access token is missing. Please reconnect your GitHub account.",
            "Integration not found": "The linked GitHub integration no longer exists. Please reconnect your GitHub account.",
            "Missing integration ID": "Integration ID is not configured. Please reconnect your GitHub account.",
        }

    def _get_access_token(self, config: GithubSourceConfig, team_id: int) -> str:
        if config.auth_method.selection == "pat":
            if not config.auth_method.personal_access_token:
                raise ValueError("Missing personal access token")
            return config.auth_method.personal_access_token

        if not config.auth_method.github_integration_id:
            raise ValueError("Missing GitHub integration ID")
        integration = self.get_oauth_integration(config.auth_method.github_integration_id, team_id)

        github_integration = GitHubIntegration(integration)
        if github_integration.access_token_expired():
            github_integration.refresh_access_token()

        if not integration.access_token:
            raise ValueError("GitHub access token not found")
        return integration.access_token

    def _egress_identity(self, config: GithubSourceConfig, team_id: int) -> GithubEgressIdentity:
        """Resolve the installation id used to gate egress and label telemetry. Empty on the PAT path
        (no installation budget, token-blind), which makes the source record counter-only and skip the
        limiter — the pre-limiter behavior. The integration is a cheap PK lookup; resolving it separately
        from the token keeps ``_get_access_token`` a token-only method (and its tests untouched), at the
        cost of one extra indexed query per pipeline build (negligible)."""
        if config.auth_method.selection == "pat" or not config.auth_method.github_integration_id:
            return GithubEgressIdentity()
        integration = self.get_oauth_integration(config.auth_method.github_integration_id, team_id)
        return GithubEgressIdentity(installation_id=GitHubIntegration(integration).github_installation_id)

    @staticmethod
    def _schema_for_endpoint(endpoint: str) -> SourceSchema:
        webhook_capable = endpoint in GITHUB_WEBHOOK_RESOURCE_MAP
        # An endpoint whose poll does no first-sync backfill (initial_lookback_days == 0,
        # i.e. workflow_jobs and reviews) can only ever be populated by the webhook: the
        # per-parent fan-out is too expensive to backfill at volume. Offer it as webhook-only
        # so users can't pick a poll mode that would sync an empty table forever. workflow_runs
        # keeps its poll backfill; the webhook just replaces re-polling for it.
        webhook_only = webhook_capable and GITHUB_ENDPOINTS[endpoint].initial_lookback_days == 0
        supports_poll = bool(INCREMENTAL_FIELDS.get(endpoint)) and not webhook_only
        return SourceSchema(
            name=endpoint,
            supports_incremental=supports_poll,
            supports_append=supports_poll,
            supports_webhooks=webhook_capable,
            webhook_only=webhook_only,
            incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            should_sync_default=GITHUB_ENDPOINTS[endpoint].should_sync_default,
        )

    def get_schemas(
        self,
        config: GithubSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [self._schema_for_endpoint(endpoint) for endpoint in list(ENDPOINTS)]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def get_endpoint_permissions(
        self, config: GithubSourceConfig, team_id: int, endpoints: list[str]
    ) -> dict[str, str | None]:
        # Only the org-scoped tables (teams, team_members) can be denied by a missing org grant; the
        # repo-scoped tables are already covered by validate_credentials at create. Probe the org
        # endpoint once and report the same reason for whichever org tables were requested, so a
        # repo-scoped connection sees exactly which tables need the extra grant and can deselect them.
        result: dict[str, str | None] = dict.fromkeys(endpoints)
        org_endpoints = [name for name in endpoints if name in ORG_SCOPED_ENDPOINTS]
        if not org_endpoints:
            return result
        try:
            access_token = self._get_access_token(config, team_id)
            egress_identity = self._egress_identity(config, team_id)
        except Exception as e:
            # A broken credential (deleted integration, suspended installation) must become a
            # per-table reason here rather than propagate: the schema-picker caller swallows
            # exceptions and falls back to "all reachable", which would show the org tables as
            # available and defer the failure to sync time. Reuse the curated wording, like
            # validate_credentials does.
            raw = str(e)
            credential_reason = next(
                (
                    friendly
                    for pattern, friendly in self.get_non_retryable_errors().items()
                    if friendly and pattern in raw
                ),
                raw,
            )
            for name in org_endpoints:
                result[name] = credential_reason
            return result
        reason = check_org_endpoint_permission(access_token, config.repository, egress_identity)
        for name in org_endpoints:
            result[name] = reason
        return result

    def validate_credentials(
        self, config: GithubSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        try:
            access_token = self._get_access_token(config, team_id)
            return validate_github_credentials(access_token, config.repository)
        except Exception as e:
            # `_get_access_token` and the OAuth mixin raise deterministic config/credential errors
            # (missing integration ID, missing token, integration deleted). The user-facing wording
            # already lives in `get_non_retryable_errors`; reuse it so this path doesn't leak the
            # internal developer string to the wizard. Fall back to the raw message if unmapped.
            raw = str(e)
            for pattern, friendly in self.get_non_retryable_errors().items():
                if friendly and pattern in raw:
                    return False, friendly
            return False, raw

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[GithubResumeConfig]:
        return ResumableSourceManager[GithubResumeConfig](inputs, GithubResumeConfig)

    def get_webhook_source_manager(self, inputs: SourceInputs) -> WebhookSourceManager:
        return WebhookSourceManager(inputs, inputs.logger)

    def get_desired_webhook_events(
        self, config: GithubSourceConfig, eligible_schema_names: list[str]
    ) -> list[str] | None:
        # Map the eligible schemas to GitHub event names (e.g. ["workflow_job", "workflow_run"]).
        return [
            GITHUB_WEBHOOK_RESOURCE_MAP[name] for name in eligible_schema_names if name in GITHUB_WEBHOOK_RESOURCE_MAP
        ]

    def create_webhook(self, config: GithubSourceConfig, webhook_url: str, team_id: int) -> WebhookCreationResult:
        access_token = self._get_access_token(config, team_id)
        # GitHub's webhook secret is creator-supplied, so we mint one, hand it to GitHub as the
        # hook's config.secret, and return it via extra_inputs so it lands on the hog function for
        # signature verification. (Contrast Stripe, which generates and returns its own secret.)
        secret = secrets.token_hex(32)
        # Always subscribe to every webhook-capable event, not just the enabled schemas: jobs fan
        # out under runs so the workflow pair travels together, and an unmapped event no-ops in the
        # hog function anyway, so over-subscribing is harmless while enabling a table later is free.
        events = self.get_desired_webhook_events(config, list(GITHUB_WEBHOOK_RESOURCE_MAP.keys())) or []
        return create_repo_webhook(access_token, config.repository, webhook_url, events, secret=secret)

    def sync_webhook_events(
        self,
        config: GithubSourceConfig,
        webhook_url: str,
        team_id: int,
        eligible_schema_names: list[str],
    ) -> WebhookSyncResult:
        access_token = self._get_access_token(config, team_id)
        # Every mapped event, not just the enabled schemas': mirrors create_webhook's stance
        # (over-subscribing is harmless, unmapped events no-op in the hog function) and auto-heals
        # webhooks created before GITHUB_WEBHOOK_RESOURCE_MAP gained new events. Thread the
        # installation identity so the hook list and PATCH draw from the same shared egress
        # budget as the data plane; PAT sources resolve to an empty identity (record-only).
        desired_events = self.get_desired_webhook_events(config, list(GITHUB_WEBHOOK_RESOURCE_MAP.keys())) or []
        return update_repo_webhook(
            access_token,
            config.repository,
            webhook_url,
            desired_events,
            egress_identity=self._egress_identity(config, team_id),
        )

    def delete_webhook(self, config: GithubSourceConfig, webhook_url: str, team_id: int) -> WebhookDeletionResult:
        access_token = self._get_access_token(config, team_id)
        return delete_repo_webhook(
            access_token, config.repository, webhook_url, egress_identity=self._egress_identity(config, team_id)
        )

    def get_external_webhook_info(
        self, config: GithubSourceConfig, webhook_url: str, team_id: int
    ) -> ExternalWebhookInfo:
        access_token = self._get_access_token(config, team_id)
        return get_repo_webhook_info(
            access_token, config.repository, webhook_url, egress_identity=self._egress_identity(config, team_id)
        )

    def source_for_pipeline(
        self,
        config: GithubSourceConfig,
        resumable_source_manager: ResumableSourceManager[GithubResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        access_token = self._get_access_token(config, inputs.team_id)
        egress_identity = self._egress_identity(config, inputs.team_id)
        # Only the workflow schemas can be webhook-fed, so skip building the manager — and its
        # webhook_enabled() DB lookup — for the poll-only endpoints (issues, commits, etc.).
        webhook_source_manager = (
            self.get_webhook_source_manager(inputs) if inputs.schema_name in GITHUB_WEBHOOK_RESOURCE_MAP else None
        )

        return github_source(
            personal_access_token=access_token,
            repository=config.repository,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
            webhook_source_manager=webhook_source_manager,
            egress_identity=egress_identity,
        )
