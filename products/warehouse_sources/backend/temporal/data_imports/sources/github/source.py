import secrets
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any, Optional, TypeVar, cast

if TYPE_CHECKING:
    from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldOauthAccountSelectConfig,
    SourceFieldOauthConfig,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
)

from posthog.models.integration import GitHubIntegration, GitHubIntegrationError

from products.warehouse_sources.backend.temporal.data_imports.naming_convention import NamingConvention
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.integration_accounts import (
    IntegrationAccount,
    IntegrationAccountListingError,
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
    delete_repo_webhook,
    ensure_repo_webhook,
    get_repo_webhook_info,
    github_source,
    update_repo_webhook,
    validate_credentials as validate_github_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.github.naming import (
    qualified_schema_name,
    resolve_schema_repo_endpoint,
    schema_metadata_for,
    split_schema_name,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.github.settings import (
    ENDPOINTS,
    GITHUB_ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

_R = TypeVar("_R")

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
    supported_versions = ("2022-11-28",)
    default_version = "2022-11-28"
    api_docs_url = "https://docs.github.com/en/rest/about-the-rest-api/api-versions"

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
                    SourceFieldOauthAccountSelectConfig(
                        name="repositories",
                        label="Repositories",
                        integrationField="github_integration_id",
                        integrationKind="github",
                        placeholder="owner/repo",
                        required=True,
                        multiple=True,
                    ),
                    # Legacy single-repo field. Kept in the config tree so pre-multi-repo sources'
                    # `job_inputs.repository` still parses (and survives read-side redaction), and
                    # doubles as the marker for the repo whose schemas keep bare, unqualified names.
                    SourceFieldOauthAccountSelectConfig(
                        name="repository",
                        label="Repository",
                        integrationField="github_integration_id",
                        integrationKind="github",
                        placeholder="owner/repo",
                        required=False,
                        hidden=True,
                    ),
                ],
            ),
            webhookSetupCaption="""To set up the webhook manually, repeat these steps for **each selected repository**, using the **same Secret** every time:

1. Go to the repository's **Settings > Webhooks** on GitHub
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
            "No repositories configured": "No repositories are selected for this source. Please update the source configuration.",
            "resolve to the same warehouse table": "Two selected repositories resolve to the same warehouse table. Please remove or rename one.",
            "Too many repositories configured": "Too many repositories are selected for this source. Please reduce the list and try again.",
            "GitHub access token not found": "GitHub OAuth access token is missing. Please reconnect your GitHub account.",
            "Integration not found": "The linked GitHub integration no longer exists. Please reconnect your GitHub account.",
            "Missing integration ID": "Integration ID is not configured. Please reconnect your GitHub account.",
        }

    def get_oauth_accounts(
        self, integration_id: int, team_id: int, search: str | None = None
    ) -> list[IntegrationAccount]:
        try:
            integration = self.get_oauth_integration(integration_id, team_id)
        except ValueError as e:
            # get_oauth_integration raises ValueError for a missing/foreign integration id — an
            # actionable customer-side state (disconnected/deleted), not a server bug.
            raise IntegrationAccountListingError(
                "The linked GitHub integration could not be found. Please reconnect your GitHub account."
            ) from e

        # `repository` is `owner/repo`. Repo lists can be large, so push the search down to the cache
        # query (server-side) and cap the page — the picker searches as the user types rather than
        # loading every repo at once.
        try:
            repositories, _has_more = GitHubIntegration(integration).list_cached_repositories(
                search=search or "", limit=100, offset=0
            )
        except GitHubIntegrationError as e:
            # The refresh talks to GitHub, which can reject the credentials, report a suspended
            # installation, or return a transient non-JSON/5xx body from its edge. None of these are
            # server bugs, so surface an actionable 400 rather than a 500 that only adds noise.
            raise IntegrationAccountListingError(
                "Couldn't load your GitHub repositories. GitHub may be temporarily unavailable, or your "
                "connection may need refreshing. Please try again, and reconnect your GitHub account if the "
                "problem persists."
            ) from e
        return [
            IntegrationAccount(value=repo["full_name"], display_name=repo["full_name"])
            for repo in repositories
            if repo.get("full_name")
        ]

    # One schema row per repository × endpoint, and — when a webhook exists — one hook per
    # repository, both fan out linearly over this list. Bound it so a single oversized/malformed
    # config (the update path accepts a large JSON body) can't drive unbounded schema creation or
    # a serial stream of GitHub hook operations. Generous versus any real use.
    MAX_REPOSITORIES = 100

    @staticmethod
    def effective_repositories(config: GithubSourceConfig) -> list[str]:
        """The repos this source syncs. `repositories` wins when set; legacy sources fall back to
        the single `repository`. Deduped, stripped, lowercased (GitHub full names are
        case-insensitive and the repo half of schema names/webhook keys must compare stably).

        Rejects a config that would resolve two repositories to the same warehouse storage, or that
        exceeds `MAX_REPOSITORIES`, so a malformed/oversized list fails fast with a curated,
        non-retryable message rather than mixing repos' data or exhausting a worker."""
        raw = config.repositories if config.repositories else ([config.repository] if config.repository else [])
        seen: set[str] = set()
        # Storage identifier (table name + S3 folder) -> the repo that claimed it. Two repositories
        # that collapse to the same identifier — the classic case is `owner/repo.name` vs
        # `owner/repo__name`, which the separator flattening isn't injective over — would share one
        # table and folder, silently mixing their data. Reject rather than merge.
        storage_owners: dict[str, str] = {}
        repositories: list[str] = []
        for repo in raw:
            normalized = repo.strip().lower()
            if not normalized or normalized in seen:
                continue
            storage_key = NamingConvention.normalize_identifier(normalized)
            if storage_key in storage_owners:
                raise ValueError(
                    f"Repositories '{storage_owners[storage_key]}' and '{normalized}' resolve to the "
                    "same warehouse table; remove or rename one."
                )
            storage_owners[storage_key] = normalized
            seen.add(normalized)
            repositories.append(normalized)
        if not repositories:
            raise ValueError("No repositories configured")
        if len(repositories) > GithubSource.MAX_REPOSITORIES:
            raise ValueError(
                f"Too many repositories configured ({len(repositories)}); the maximum is "
                f"{GithubSource.MAX_REPOSITORIES}."
            )
        return repositories

    @staticmethod
    def is_legacy_bare_repo(config: GithubSourceConfig, repository: str) -> bool:
        """True when `repository` is the pre-multi-repo repo whose schemas keep bare, unqualified
        names (`issues`, not `owner/repo.issues`)."""
        return bool(config.repository) and repository == (config.repository or "").strip().lower()

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
    def _schema_for_endpoint(endpoint: str, repository: str | None = None) -> SourceSchema:
        webhook_capable = endpoint in GITHUB_WEBHOOK_RESOURCE_MAP
        # An endpoint whose poll does no first-sync backfill (initial_lookback_days == 0:
        # workflow_jobs, workflow_runs, reviews) can only ever be populated by the webhook —
        # backfilling the full history is too expensive against a shared, rate-limited budget.
        # Offer it as webhook-only so users can't pick a poll mode that would sync an empty table
        # forever; the webhook replaces both re-polling and the initial history crawl.
        webhook_only = webhook_capable and GITHUB_ENDPOINTS[endpoint].initial_lookback_days == 0
        supports_poll = bool(INCREMENTAL_FIELDS.get(endpoint)) and not webhook_only
        return SourceSchema(
            name=endpoint if repository is None else qualified_schema_name(repository, endpoint),
            supports_incremental=supports_poll,
            supports_append=supports_poll,
            supports_webhooks=webhook_capable,
            webhook_only=webhook_only,
            incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            should_sync_default=GITHUB_ENDPOINTS[endpoint].should_sync_default,
            label=None if repository is None else f"{repository} · {endpoint}",
            schema_metadata=None if repository is None else schema_metadata_for(repository, endpoint),
        )

    def get_schemas(
        self,
        config: GithubSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # One row per repo × endpoint. The legacy single-repo repo (pre-multi-repo sources)
        # keeps bare endpoint names so its existing rows, tables, and saved queries never
        # change; every other repo gets `owner/repo.endpoint` qualified names.
        schemas = [
            self._schema_for_endpoint(endpoint, repository=None if self.is_legacy_bare_repo(config, repo) else repo)
            for repo in self.effective_repositories(config)
            for endpoint in list(ENDPOINTS)
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def get_endpoint_permissions(
        self, config: GithubSourceConfig, team_id: int, endpoints: list[str]
    ) -> dict[str, str | None]:
        # Only the org-scoped tables (teams, team_members) can be denied by a missing org grant; the
        # repo-scoped tables are already covered by validate_credentials at create. Inputs may be
        # bare (`teams`) or repo-qualified (`owner/repo.teams`); probe the org endpoint once per
        # unique owner and fan the reason back per input name, so a repo-scoped connection sees
        # exactly which tables need the extra grant and can deselect them.
        result: dict[str, str | None] = dict.fromkeys(endpoints)
        org_endpoints: dict[str, str] = {}  # input name -> repository to probe through
        for name in endpoints:
            repository, endpoint = split_schema_name(name)
            if endpoint not in ORG_SCOPED_ENDPOINTS:
                continue
            org_endpoints[name] = (repository or config.repository or "").strip().lower()
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
        reason_by_owner: dict[str, str | None] = {}
        for name, repository in org_endpoints.items():
            owner = repository.split("/", 1)[0]
            if owner not in reason_by_owner:
                reason_by_owner[owner] = check_org_endpoint_permission(access_token, repository, egress_identity)
            result[name] = reason_by_owner[owner]
        return result

    # Bound so a source with hundreds of repos doesn't turn the wizard's validate round-trip
    # into hundreds of serial GitHub calls; repos beyond the cap fail at sync time instead.
    MAX_VALIDATED_REPOSITORIES = 20

    def validate_credentials(
        self, config: GithubSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        try:
            access_token = self._get_access_token(config, team_id)
            repositories = self.effective_repositories(config)
            failures: list[str] = []
            for repository in repositories[: self.MAX_VALIDATED_REPOSITORIES]:
                is_valid, message = validate_github_credentials(access_token, repository)
                if is_valid:
                    continue
                # A 401 is token-level — probing further repos yields the same answer.
                if message == "Invalid personal access token":
                    return False, message
                failures.append(message or f"Repository '{repository}' not found or not accessible")
            if failures:
                return False, "; ".join(failures)
            return True, None
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

    def webhook_mapping_key(self, schema_name: str) -> str:
        # Legacy bare rows keep the bare event key (`workflow_run`); repo-qualified rows get
        # `owner/repo.event` so two repos' rows for the same event don't collide. The hog template
        # looks up `lower(repository.full_name) + '.' + eventType` first, then the bare event.
        repository, endpoint = split_schema_name(schema_name)
        event = GITHUB_WEBHOOK_RESOURCE_MAP.get(endpoint, endpoint)
        if repository is None:
            return event
        return f"{repository.strip().lower()}.{event}"

    def webhook_template_inputs(self, config: GithubSourceConfig) -> dict[str, Any]:
        # Pin the legacy repository (the one whose rows keep bare event keys) so the template's
        # bare-key fallback only fires for its events. Empty when there's no legacy repo (pure
        # multi-repo sources have no bare keys, so nothing to bind).
        return {"legacy_repository": (config.repository or "").strip().lower()}

    def get_desired_webhook_events(
        self, config: GithubSourceConfig, eligible_schema_names: list[str]
    ) -> list[str] | None:
        # Map the eligible schemas — bare or repo-qualified — to GitHub event names
        # (e.g. ["workflow_job", "workflow_run"]), deduped since every repo shares one event set.
        events: list[str] = []
        for name in eligible_schema_names:
            _, endpoint = split_schema_name(name)
            event = GITHUB_WEBHOOK_RESOURCE_MAP.get(endpoint)
            if event is not None and event not in events:
                events.append(event)
        return events

    def _webhook_repositories(self, config: GithubSourceConfig) -> list[str]:
        return self.effective_repositories(config)

    # The webhook operations run 1-2 GitHub calls per repo inside synchronous request handlers
    # (create/delete/info actions, and the repo-list reconcile inside the source PATCH). A source
    # can carry up to MAX_REPOSITORIES repos, so the per-repo calls fan out on a bounded pool
    # instead of running serially — capping the repo list here would leave webhooks unmanaged.
    _WEBHOOK_CONCURRENCY = 8

    def _map_webhook_repositories(self, repositories: list[str], fn: Callable[[str], _R]) -> list[_R]:
        """Run ``fn`` per repo on a bounded thread pool, preserving repo order."""
        if len(repositories) <= 1:
            return [fn(repository) for repository in repositories]
        with ThreadPoolExecutor(max_workers=min(self._WEBHOOK_CONCURRENCY, len(repositories))) as pool:
            return list(pool.map(fn, repositories))

    def ensure_webhooks_for_repositories(
        self, config: GithubSourceConfig, webhook_url: str, team_id: int, repositories: list[str], secret: str
    ) -> list[str]:
        """Idempotently create/update hooks in the given repos, pinned to the source's existing
        signing secret. Used by the repo-list reconcile for newly added repos. Returns per-repo
        failure messages (empty on full success)."""
        access_token = self._get_access_token(config, team_id)
        egress_identity = self._egress_identity(config, team_id)
        events = self.get_desired_webhook_events(config, list(GITHUB_WEBHOOK_RESOURCE_MAP.keys())) or []
        results = self._map_webhook_repositories(
            repositories,
            lambda repository: ensure_repo_webhook(
                access_token, repository, webhook_url, events, secret=secret, egress_identity=egress_identity
            ),
        )
        return [
            f"{repository}: {result.error}" for repository, result in zip(repositories, results) if not result.success
        ]

    def delete_webhooks_for_repositories(
        self, config: GithubSourceConfig, webhook_url: str, team_id: int, repositories: list[str]
    ) -> list[str]:
        """Delete this source's hook from the given repos (repo-list reconcile, removed repos).
        Returns per-repo failure messages (empty on full success)."""
        access_token = self._get_access_token(config, team_id)
        egress_identity = self._egress_identity(config, team_id)
        results = self._map_webhook_repositories(
            repositories,
            lambda repository: delete_repo_webhook(
                access_token, repository, webhook_url, egress_identity=egress_identity
            ),
        )
        return [
            f"{repository}: {result.error}" for repository, result in zip(repositories, results) if not result.success
        ]

    def create_webhook(self, config: GithubSourceConfig, webhook_url: str, team_id: int) -> WebhookCreationResult:
        access_token = self._get_access_token(config, team_id)
        egress_identity = self._egress_identity(config, team_id)
        # GitHub's webhook secret is creator-supplied, so we mint one, hand it to GitHub as the
        # hook's config.secret, and return it via extra_inputs so it lands on the hog function for
        # signature verification. (Contrast Stripe, which generates and returns its own secret.)
        # One secret is shared by every repo's hook — the source has a single hog function with a
        # single signing_secret input, and repos added later are pinned to the same secret.
        secret = secrets.token_hex(32)
        # Always subscribe to every webhook-capable event, not just the enabled schemas: jobs fan
        # out under runs so the workflow pair travels together, and an unmapped event no-ops in the
        # hog function anyway, so over-subscribing is harmless while enabling a table later is free.
        events = self.get_desired_webhook_events(config, list(GITHUB_WEBHOOK_RESOURCE_MAP.keys())) or []
        repositories = self._webhook_repositories(config)
        results = self._map_webhook_repositories(
            repositories,
            lambda repository: ensure_repo_webhook(
                access_token, repository, webhook_url, events, secret=secret, egress_identity=egress_identity
            ),
        )
        any_success = any(result.success for result in results)
        failures = [
            f"{repository}: {result.error}" for repository, result in zip(repositories, results) if not result.success
        ]
        if not failures:
            return WebhookCreationResult(success=True, extra_inputs={"signing_secret": secret})
        # Partial success still persists the secret: the repos that did get a hook must verify
        # against it, and the failed repos' manual setup instructions tell the user to reuse it.
        return WebhookCreationResult(
            success=False,
            error="Failed to create the webhook in some repositories — " + "; ".join(failures),
            extra_inputs={"signing_secret": secret} if any_success else {},
        )

    def sync_webhook_events(
        self,
        config: GithubSourceConfig,
        webhook_url: str,
        team_id: int,
        eligible_schema_names: list[str],
    ) -> WebhookSyncResult:
        access_token = self._get_access_token(config, team_id)
        egress_identity = self._egress_identity(config, team_id)
        # Every mapped event, not just the enabled schemas': mirrors create_webhook's stance
        # (over-subscribing is harmless, unmapped events no-op in the hog function) and auto-heals
        # webhooks created before GITHUB_WEBHOOK_RESOURCE_MAP gained new events. Thread the
        # installation identity so the hook list and PATCH draw from the same shared egress
        # budget as the data plane; PAT sources resolve to an empty identity (record-only).
        desired_events = self.get_desired_webhook_events(config, list(GITHUB_WEBHOOK_RESOURCE_MAP.keys())) or []
        repositories = self._webhook_repositories(config)
        results = self._map_webhook_repositories(
            repositories,
            lambda repository: update_repo_webhook(
                access_token, repository, webhook_url, desired_events, egress_identity=egress_identity
            ),
        )
        failures = [
            f"{repository}: {result.error}" for repository, result in zip(repositories, results) if not result.success
        ]
        if not failures:
            return WebhookSyncResult(success=True)
        return WebhookSyncResult(success=False, error="; ".join(failures))

    def delete_webhook(self, config: GithubSourceConfig, webhook_url: str, team_id: int) -> WebhookDeletionResult:
        access_token = self._get_access_token(config, team_id)
        egress_identity = self._egress_identity(config, team_id)
        repositories = self._webhook_repositories(config)
        results = self._map_webhook_repositories(
            repositories,
            lambda repository: delete_repo_webhook(
                access_token, repository, webhook_url, egress_identity=egress_identity
            ),
        )
        failures = [
            f"{repository}: {result.error}" for repository, result in zip(repositories, results) if not result.success
        ]
        if not failures:
            return WebhookDeletionResult(success=True)
        return WebhookDeletionResult(success=False, error="; ".join(failures))

    def get_external_webhook_info(
        self, config: GithubSourceConfig, webhook_url: str, team_id: int
    ) -> ExternalWebhookInfo:
        access_token = self._get_access_token(config, team_id)
        egress_identity = self._egress_identity(config, team_id)
        # exists=True only when every repo carries the hook; partial coverage surfaces the
        # missing repos so the UI can prompt a re-create (which is idempotent per repo).
        missing: list[str] = []
        errors: list[str] = []
        merged_events: set[str] = set()
        first_info: ExternalWebhookInfo | None = None
        repositories = self._webhook_repositories(config)
        infos = self._map_webhook_repositories(
            repositories,
            lambda repository: get_repo_webhook_info(
                access_token, repository, webhook_url, egress_identity=egress_identity
            ),
        )
        for repository, info in zip(repositories, infos):
            if info.error:
                errors.append(f"{repository}: {info.error}")
            elif not info.exists:
                missing.append(repository)
            else:
                merged_events.update(info.enabled_events or [])
                if first_info is None:
                    first_info = info
        if errors:
            return ExternalWebhookInfo(exists=False, error="; ".join(errors))
        if missing:
            if first_info is None:
                return ExternalWebhookInfo(exists=False)
            return ExternalWebhookInfo(
                exists=False,
                url=webhook_url,
                enabled_events=sorted(merged_events),
                error="Webhook missing in repositories: " + ", ".join(missing),
            )
        if first_info is None:
            return ExternalWebhookInfo(exists=False)
        return ExternalWebhookInfo(
            exists=True,
            url=webhook_url,
            enabled_events=sorted(merged_events),
            status=first_info.status,
            created_at=first_info.created_at,
        )

    def source_for_pipeline(
        self,
        config: GithubSourceConfig,
        resumable_source_manager: ResumableSourceManager[GithubResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        access_token = self._get_access_token(config, inputs.team_id)
        egress_identity = self._egress_identity(config, inputs.team_id)
        repository, endpoint = resolve_schema_repo_endpoint(inputs.schema_metadata, inputs.schema_name, config)
        # Only the workflow schemas can be webhook-fed, so skip building the manager — and its
        # webhook_enabled() DB lookup — for the poll-only endpoints (issues, commits, etc.).
        webhook_source_manager = (
            self.get_webhook_source_manager(inputs) if endpoint in GITHUB_WEBHOOK_RESOURCE_MAP else None
        )

        # Storage identity mirrors the SQL sources' resolve_source_location: prefer the row's
        # pinned s3_folder_name so a rename never orphans Delta data; normalize the (possibly
        # repo-qualified) schema name otherwise. Legacy bare rows normalize to today's value.
        storage_key = (
            inputs.s3_folder_name if isinstance(inputs.s3_folder_name, str) and inputs.s3_folder_name else None
        )
        response_name = NamingConvention.normalize_identifier(storage_key or inputs.schema_name)

        return github_source(
            personal_access_token=access_token,
            repository=repository,
            endpoint=endpoint,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
            webhook_source_manager=webhook_source_manager,
            egress_identity=egress_identity,
            response_name=response_name,
        )
