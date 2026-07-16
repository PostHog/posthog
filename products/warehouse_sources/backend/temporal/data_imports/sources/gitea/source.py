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
)

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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import ValidateDatabaseHostMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import GiteaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.gitea.gitea import (
    GiteaResumeConfig,
    create_repo_webhook,
    delete_repo_webhook,
    get_repo_webhook_info,
    gitea_source,
    hostname_of,
    update_repo_webhook_events,
    validate_credentials as validate_gitea_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.gitea.settings import (
    ENDPOINTS,
    GITEA_ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

# Schemas that can be fed by Gitea webhooks, mapped to the X-Gitea-Event header value the
# webhook handler routes on (schema_mapping is keyed by these values).
GITEA_WEBHOOK_RESOURCE_MAP: dict[str, str] = {
    name: config.webhook_event for name, config in GITEA_ENDPOINTS.items() if config.webhook_event is not None
}


@SourceRegistry.register
class GiteaSource(
    ResumableSource[GiteaSourceConfig, GiteaResumeConfig],
    WebhookSource[GiteaSourceConfig],
    ValidateDatabaseHostMixin,
):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.GITEA

    @property
    def connection_host_fields(self) -> list[str]:
        # `base_url` decides where the stored token is sent; `repository` decides which repo that
        # token reads. Retargeting either lets an editor reuse a token they never entered against a
        # host they control or a private repo the token can reach — both must re-require the token.
        return ["base_url", "repository"]

    @property
    def webhook_template(self) -> Optional["HogFunctionTemplateDC"]:
        from products.warehouse_sources.backend.temporal.data_imports.sources.gitea.webhook_template import template

        return template

    @property
    def webhook_resource_map(self) -> dict[str, str]:
        return GITEA_WEBHOOK_RESOURCE_MAP

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.GITEA,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Gitea",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Connect a repository on your Gitea (or Forgejo) instance to sync issues, pull requests, commits, and more.

Create an access token under **Settings > Applications** on your instance with read access to the repository (the `read:repository` and `read:issue` scopes). The instance URL is your Gitea host, e.g. `https://gitea.example.com` — it must be reachable over https from the internet.""",
            iconPath="/static/services/gitea.png",
            docsUrl="https://posthog.com/docs/cdp/sources/gitea",
            keywords=["forgejo", "git"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="base_url",
                        label="Instance URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="https://gitea.example.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="access_token",
                        label="Access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
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

1. Go to your repository's **Settings > Webhooks** on your Gitea instance
2. Click **Add webhook** and choose **Gitea**
3. Paste the webhook URL shown below into the **Target URL** field
4. Set **HTTP method** to **POST** and **POST content type** to **application/json**
5. Enter a **Secret** and add the same value to the **Signing secret** field below
6. Under **Trigger on**, choose **Custom events** and tick **Issues** and **Pull request**
7. Click **Add webhook**

If automatic creation failed, your token needs admin access to the repository — add it and reconnect, or set the webhook up manually using the steps above.""",
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.gitea.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your Gitea access token is invalid or expired. Please generate a new token and reconnect.",
            "403 Client Error": "Your Gitea token does not have permission to access this resource. Please check the token's scopes and repository access.",
            "404 Client Error": "Repository not found. Please verify the instance URL, repository name, and token access.",
            "Invalid Gitea instance URL": "The Gitea instance URL is invalid. Please enter the instance's canonical https URL.",
        }

    def get_schemas(
        self,
        config: GiteaSourceConfig,
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
                supports_webhooks=endpoint in GITEA_WEBHOOK_RESOURCE_MAP,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: GiteaSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        try:
            host_valid, host_error = self.is_database_host_valid(hostname_of(config.base_url), team_id)
        except ValueError:
            return False, "Invalid Gitea instance URL"
        if not host_valid:
            return False, host_error

        return validate_gitea_credentials(config.base_url, config.access_token, config.repository)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[GiteaResumeConfig]:
        return ResumableSourceManager[GiteaResumeConfig](inputs, GiteaResumeConfig)

    def get_webhook_source_manager(self, inputs: SourceInputs) -> WebhookSourceManager:
        return WebhookSourceManager(inputs, inputs.logger)

    def get_desired_webhook_events(
        self, config: GiteaSourceConfig, eligible_schema_names: list[str]
    ) -> list[str] | None:
        return [
            GITEA_WEBHOOK_RESOURCE_MAP[name] for name in eligible_schema_names if name in GITEA_WEBHOOK_RESOURCE_MAP
        ]

    def create_webhook(self, config: GiteaSourceConfig, webhook_url: str, team_id: int) -> WebhookCreationResult:
        # Gitea's webhook secret is creator-supplied, so mint one, hand it to Gitea as the
        # hook's config.secret, and return it via extra_inputs so it lands on the hog
        # function for signature verification.
        secret = secrets.token_hex(32)
        # Subscribe to every webhook-capable event, not just the enabled schemas: an
        # unmapped event no-ops in the hog function, so over-subscribing is harmless while
        # enabling a table later is free.
        events = self.get_desired_webhook_events(config, list(GITEA_WEBHOOK_RESOURCE_MAP.keys())) or []
        return create_repo_webhook(config.base_url, config.access_token, config.repository, webhook_url, events, secret)

    def sync_webhook_events(
        self,
        config: GiteaSourceConfig,
        webhook_url: str,
        team_id: int,
        eligible_schema_names: list[str],
    ) -> WebhookSyncResult:
        # Every mapped event, not just the enabled schemas': mirrors create_webhook's stance
        # and auto-heals webhooks created before GITEA_WEBHOOK_RESOURCE_MAP gained new events.
        desired_events = self.get_desired_webhook_events(config, list(GITEA_WEBHOOK_RESOURCE_MAP.keys())) or []
        return update_repo_webhook_events(
            config.base_url, config.access_token, config.repository, webhook_url, desired_events
        )

    def delete_webhook(self, config: GiteaSourceConfig, webhook_url: str, team_id: int) -> WebhookDeletionResult:
        return delete_repo_webhook(config.base_url, config.access_token, config.repository, webhook_url)

    def get_external_webhook_info(
        self, config: GiteaSourceConfig, webhook_url: str, team_id: int
    ) -> ExternalWebhookInfo:
        return get_repo_webhook_info(config.base_url, config.access_token, config.repository, webhook_url)

    def source_for_pipeline(
        self,
        config: GiteaSourceConfig,
        resumable_source_manager: ResumableSourceManager[GiteaResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        host_valid, host_error = self.is_database_host_valid(hostname_of(config.base_url), inputs.team_id)
        if not host_valid:
            raise ValueError(host_error or "Invalid Gitea host")

        # Only the webhook-capable schemas need the manager — skip its webhook_enabled()
        # DB lookup for the poll-only endpoints (commits, releases, ...).
        webhook_source_manager = (
            self.get_webhook_source_manager(inputs) if inputs.schema_name in GITEA_WEBHOOK_RESOURCE_MAP else None
        )

        return gitea_source(
            base_url=config.base_url,
            access_token=config.access_token,
            repository=config.repository,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            webhook_source_manager=webhook_source_manager,
        )
