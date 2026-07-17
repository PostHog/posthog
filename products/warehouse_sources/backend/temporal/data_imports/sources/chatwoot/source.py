from typing import TYPE_CHECKING, Optional, cast

import structlog

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
from products.warehouse_sources.backend.temporal.data_imports.sources.chatwoot.chatwoot import (
    HOST_NOT_ALLOWED_ERROR,
    HTTP_NOT_ALLOWED_ERROR,
    INVALID_ACCOUNT_ID_ERROR,
    RESPONSE_TOO_LARGE_ERROR,
    RESPONSE_TOO_SLOW_ERROR,
    ChatwootResumeConfig,
    chatwoot_source,
    create_webhook as create_chatwoot_webhook,
    delete_webhook as delete_chatwoot_webhook,
    get_external_webhook_info as get_chatwoot_webhook_info,
    update_webhook_events as update_chatwoot_webhook_events,
    validate_credentials as validate_chatwoot_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.chatwoot.settings import (
    CHATWOOT_ENDPOINTS,
    ENDPOINTS,
    RESOURCE_TO_WEBHOOK_OBJECT_TYPE,
    all_webhook_events,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import ChatwootSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType

# Webhook management calls run in the API request path where no job logger exists.
logger = structlog.get_logger(__name__)


@SourceRegistry.register
class ChatwootSource(
    ResumableSource[ChatwootSourceConfig, ChatwootResumeConfig],
    WebhookSource[ChatwootSourceConfig],
):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CHATWOOT

    @property
    def connection_host_fields(self) -> list[str]:
        # `host` determines where the stored access token is sent, and `account_id` selects which
        # Chatwoot account it reads — a single user token can belong to several accounts, so
        # retargeting either must re-require the token rather than reusing the preserved one.
        return ["host", "account_id"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.CHATWOOT,
            category=DataWarehouseSourceCategory.CUSTOMER_SUPPORT,
            label="Chatwoot",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Sync conversations, messages, contacts, agents, and more from Chatwoot into the PostHog Data warehouse.

Copy your API access token from **Profile settings → Access token** in Chatwoot. Use an administrator's token: agent tokens only see their assigned inboxes, and only administrators can manage webhooks.

Your account ID is the number in your Chatwoot URL, e.g. `app.chatwoot.com/app/accounts/<account ID>`.

For self-hosted Chatwoot, set your instance URL (for example `https://chatwoot.example.com`); leave it empty for Chatwoot Cloud.""",
            iconPath="/static/services/chatwoot.png",
            docsUrl="https://posthog.com/docs/cdp/sources/chatwoot",
            keywords=["live chat", "helpdesk", "customer support"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="host",
                        label="Chatwoot instance URL",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="https://app.chatwoot.com",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="account_id",
                        label="Account ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="1",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="api_access_token",
                        label="API access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
            webhookSetupCaption="""To set up the webhook manually:

1. In Chatwoot, go to **Settings → Integrations → Webhooks** and click **Configure**
2. Click **Add new webhook** and paste the webhook URL shown below
3. Subscribe to the conversation and message events (`conversation_created`, `conversation_updated`, `conversation_status_changed`, `message_created`, `message_updated`)

Recent Chatwoot versions sign deliveries with a per-webhook secret — fetch it from `GET /api/v1/accounts/{account_id}/webhooks` and paste it into the signing secret field below. Older self-hosted versions do not sign deliveries; enable the bypass toggle on the webhook function instead.

If automatic creation failed, note that only Chatwoot administrators can manage webhooks — use an administrator's API access token.""",
            webhookFields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="signing_secret",
                        label="Signing secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.chatwoot.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    @property
    def webhook_template(self) -> Optional["HogFunctionTemplateDC"]:
        from products.warehouse_sources.backend.temporal.data_imports.sources.chatwoot.webhook_template import (  # noqa: PLC0415
            template,
        )

        return template

    @property
    def webhook_resource_map(self) -> dict[str, str]:
        return RESOURCE_TO_WEBHOOK_OBJECT_TYPE

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # The base URL is installation-specific, so match on the stable status text rather than a
        # fixed host. Fan-out 404s (a conversation deleted mid-sync) are skipped in the transport,
        # so a surviving 404 means the account ID or instance URL is wrong.
        return {
            "401 Client Error": "Chatwoot rejected your API access token. Check the token is correct, has not been revoked, and belongs to a member of the configured account, then reconnect.",
            "403 Client Error": "Your Chatwoot API access token does not have permission to read this data. Use an administrator's access token, then reconnect.",
            "404 Client Error": "Chatwoot could not find the configured account. Check the account ID and instance URL, then reconnect.",
            INVALID_ACCOUNT_ID_ERROR: "The Chatwoot account ID must be a number (the number in your Chatwoot URL, e.g. app.chatwoot.com/app/accounts/1). Update the source configuration.",
            HOST_NOT_ALLOWED_ERROR: "The Chatwoot host is not allowed. Please use a publicly reachable instance URL.",
            HTTP_NOT_ALLOWED_ERROR: "The Chatwoot host must use HTTPS. Please update the instance URL to use https://.",
            RESPONSE_TOO_LARGE_ERROR: "Chatwoot returned a response that was too large to process. Please contact support if this persists.",
            RESPONSE_TOO_SLOW_ERROR: "Chatwoot took too long to send a response. Check that the instance URL points at a healthy Chatwoot server, then try again.",
        }

    def get_schemas(
        self,
        config: ChatwootSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Chatwoot's list endpoints expose no server-side timestamp filter, so every schema is
        # full refresh; conversations and messages additionally support webhook-fed deltas.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
                supports_webhooks=CHATWOOT_ENDPOINTS[endpoint].supports_webhooks,
                description=CHATWOOT_ENDPOINTS[endpoint].description,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: ChatwootSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        # The user token grants access to the whole account, so one probe validates every schema.
        return validate_chatwoot_credentials(config.host, config.account_id, config.api_access_token, team_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ChatwootResumeConfig]:
        return ResumableSourceManager[ChatwootResumeConfig](inputs, ChatwootResumeConfig)

    def get_webhook_source_manager(self, inputs: SourceInputs) -> WebhookSourceManager:
        return WebhookSourceManager(inputs, inputs.logger)

    def create_webhook(
        self, config: ChatwootSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> WebhookCreationResult:
        return create_chatwoot_webhook(
            config.host, config.account_id, config.api_access_token, webhook_url, team_id, logger
        )

    def get_desired_webhook_events(
        self, config: ChatwootSourceConfig, eligible_schema_names: list[str]
    ) -> list[str] | None:
        # Every mappable event, not just the selected tables — auto-heals webhooks created before
        # RESOURCE_TO_WEBHOOK_EVENTS gained new resources.
        return all_webhook_events()

    def sync_webhook_events(
        self,
        config: ChatwootSourceConfig,
        webhook_url: str,
        team_id: int,
        eligible_schema_names: list[str],
        api_version: str | None = None,
    ) -> WebhookSyncResult:
        desired_events = self.get_desired_webhook_events(config, eligible_schema_names) or []
        return update_chatwoot_webhook_events(
            config.host, config.account_id, config.api_access_token, webhook_url, desired_events, team_id, logger
        )

    def get_external_webhook_info(
        self, config: ChatwootSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> ExternalWebhookInfo:
        return get_chatwoot_webhook_info(
            config.host, config.account_id, config.api_access_token, webhook_url, team_id, logger
        )

    def delete_webhook(
        self, config: ChatwootSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> WebhookDeletionResult:
        return delete_chatwoot_webhook(
            config.host, config.account_id, config.api_access_token, webhook_url, team_id, logger
        )

    def source_for_pipeline(
        self,
        config: ChatwootSourceConfig,
        resumable_source_manager: ResumableSourceManager[ChatwootResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in CHATWOOT_ENDPOINTS:
            raise ValueError(f"Unknown Chatwoot schema '{inputs.schema_name}'")

        return chatwoot_source(
            host=config.host,
            account_id=config.account_id,
            api_access_token=config.api_access_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            webhook_source_manager=self.get_webhook_source_manager(inputs),
        )
