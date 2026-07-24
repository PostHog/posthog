from typing import TYPE_CHECKING, Optional, cast

if TYPE_CHECKING:
    from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC
    from posthog.models.integration import Integration

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSwitchGroupConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline.typings import (
    SourceInputs,
    SourceResponse,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.mixins import OAuthMixin
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.slack import SlackSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.slack.settings import ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.slack.slack import (
    SlackResumeConfig,
    auth_test_user_id,
    get_channels,
    join_public_channels,
    manual_cache_id,
    slack_source,
    validate_credentials as validate_slack_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SlackSource(ResumableSource[SlackSourceConfig, SlackResumeConfig], WebhookSource[SlackSourceConfig], OAuthMixin):
    api_docs_url = "https://api.slack.com/web"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SLACK

    @property
    def webhook_template(self) -> Optional["HogFunctionTemplateDC"]:
        from products.warehouse_sources.backend.temporal.data_imports.sources.slack.webhook_template import template

        return template

    @property
    def webhook_resource_map(self) -> dict[str, str]:
        # Slack channel IDs are used as both schema names and webhook event keys,
        # so this is an identity mapping. We return an empty dict and rely on the
        # fallback in get_or_create_webhook_hog_function that defaults to using
        # the schema name as the object type.
        return {}

    def get_webhook_source_manager(self, inputs: SourceInputs) -> WebhookSourceManager:
        return WebhookSourceManager(inputs, inputs.logger)

    @staticmethod
    def _get_authed_user_id(integration: "Integration") -> str | None:
        return (integration.config or {}).get("authed_user", {}).get("id")

    def _resolve_access_token(self, config: SlackSourceConfig, team_id: int) -> tuple[str, str | None, str]:
        """Resolve credentials, preferring the bring-your-own bot token.

        Returns ``(access_token, authed_user_id, cache_id)``. ``authed_user_id`` scopes private-channel
        discovery to a single user; ``cache_id`` keys the per-workspace channel-list cache.

        - A ``slack_access_token`` means the customer's own Slack app. The token is stored on the
          source itself, so it stays within Slack's API terms for internal apps. ``auth.test`` gives
          the token's own user id and a hash of the token keys the cache. This is the only path new
          sources can configure.
        - Otherwise the source predates bring-your-own and still points at PostHog's shared app
          (legacy OAuth): credentials live on the linked Integration row. Pasting a token converts
          such a source in place — the token takes precedence and the stale integration id is ignored.
        """
        if config.slack_access_token:
            access_token = config.slack_access_token
            return access_token, auth_test_user_id(access_token), manual_cache_id(access_token)

        if not config.slack_integration_id:
            raise ValueError("Slack access token not found")

        integration = self.get_oauth_integration(config.slack_integration_id, team_id)
        oauth_token = integration.access_token
        if not oauth_token:
            raise ValueError("Slack access token not found")
        return oauth_token, self._get_authed_user_id(integration), str(integration.id)

    def create_webhook(
        self, config: SlackSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> WebhookCreationResult:
        return WebhookCreationResult(
            success=False,
            error="Slack does not support automatic webhook creation. Please follow the manual setup instructions.",
        )

    def delete_webhook(
        self, config: SlackSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> WebhookDeletionResult:
        # Slack does not expose an API to remove an Events API Request URL — the user has to
        # toggle it off manually in the app settings. Returning success lets the HogFunction
        # be cleaned up without showing the user a misleading "deletion failed" error.
        return WebhookDeletionResult(success=True)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SLACK,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            caption="""Sync Slack channels, users, and messages into PostHog by connecting your own Slack app.

You create a Slack app in your workspace and paste its bot token here. Using your own app keeps message syncing within Slack's API terms — [read the docs](https://posthog.com/docs/cdp/sources/slack) for the full walkthrough.

**1. Create the app**

Open [Slack apps](https://api.slack.com/apps?new_app=1), click **From a manifest**, pick your workspace, and paste this manifest:

```json
{
    "display_information": {
        "name": "PostHog data warehouse",
        "description": "Sync Slack channels, users, and messages to PostHog data warehouse"
    },
    "oauth_config": {
        "scopes": {
            "bot": [
                "channels:read",
                "channels:join",
                "groups:read",
                "channels:history",
                "groups:history",
                "users:read",
                "users:read.email",
                "reactions:read"
            ]
        }
    },
    "settings": {
        "org_deploy_enabled": false,
        "socket_mode_enabled": false,
        "token_rotation_enabled": false
    }
}
```

**2. Install and copy the token**

Click **Install App > Install to Workspace** and authorize. Copy the **Bot User OAuth Token** (starts with `xoxb-`) and paste it below.

**3. Invite the bot**

Invite the bot to any channel whose messages you want to sync (`/invite @PostHog data warehouse`). After the source is created, follow the webhook steps to start receiving messages.""",
            iconPath="/static/services/slack.png",
            docsUrl="https://posthog.com/docs/cdp/sources/slack",
            releaseStatus=ReleaseStatus.GA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="slack_access_token",
                        label="Bot User OAuth Token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="xoxb-...",
                        caption="Found under **Settings > Install App** in the Slack app you created from the manifest above.",
                        secret=True,
                    ),
                    SourceFieldSwitchGroupConfig(
                        name="join_public_channels",
                        label="Automatically join public channels",
                        caption="On by default: the bot joins every public channel so their new messages sync without inviting it to each one. Turn it off to pick channels manually. Private channels always need a manual invite. Uses the `channels:join` scope, which the manifest above already includes.",
                        default=True,
                        fields=cast(list[FieldType], []),
                    ),
                ],
            ),
            webhookManualOnly=True,
            webhookSetupCaption="""Slack delivers new messages to PostHog through your Slack app's Event Subscriptions.

If you connected with your own Slack app (recommended), open that same app and add the Event Subscriptions below. Otherwise create a new app from the manifest.

1. Open your app (or [create one from a manifest](https://api.slack.com/apps?new_app=1))
2. Go to **Event Subscriptions**, toggle it on, and set the **Request URL** to the webhook URL shown below
3. Under **Subscribe to bot events**, add `message.channels` and `message.groups`, then **Save Changes** and reinstall if prompted
4. Open **Basic Information > App Credentials**, copy the **Signing Secret**, and paste it in the form below

Prefer a manifest? Paste this when creating the app — it wires the request URL and events for you:

```json
{
    "display_information": {
        "name": "PostHog data warehouse",
        "description": "Sync Slack channels, users, and messages to PostHog data warehouse"
    },
    "oauth_config": {
        "scopes": {
            "bot": [
                "channels:read",
                "channels:join",
                "groups:read",
                "channels:history",
                "groups:history",
                "users:read",
                "users:read.email",
                "reactions:read"
            ]
        }
    },
    "settings": {
        "event_subscriptions": {
            "request_url": "{webhook_url}",
            "bot_events": [
                "message.channels",
                "message.groups"
            ]
        },
        "org_deploy_enabled": false,
        "socket_mode_enabled": false,
        "token_rotation_enabled": false
    }
}
```""",
            webhookFields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="signing_secret",
                        label="Signing secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        secret=True,
                        placeholder="",
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.slack.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "invalid_auth": "Your Slack token is invalid. Please reconnect the source.",
            "account_inactive": "Your Slack account is inactive. Please reconnect the source.",
            "token_revoked": "Your Slack token has been revoked. Please reconnect the source.",
            "missing_scope": "Your Slack integration is missing required scopes. Please reconnect the source.",
            "not_in_channel": "The Slack bot is not a member of this channel. Please invite the bot to the channel and try again.",
            "channel_not_found": "This Slack channel was not found. It may have been deleted or the bot lacks permission to access it.",
            "Integration not found": "Your Slack integration was not found. Please reconnect the source.",
            "Slack access token not found": "Your Slack access token is missing. Please reconnect the source.",
        }

    def get_schemas(
        self,
        config: SlackSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas: list[SourceSchema] = [
            SourceSchema(
                name=name,
                supports_incremental=len(endpoint_config.incremental_fields) > 0,
                supports_append=len(endpoint_config.incremental_fields) > 0,
                incremental_fields=endpoint_config.incremental_fields,
            )
            for name, endpoint_config in ENDPOINTS.items()
        ]

        access_token, authed_user, cache_id = self._resolve_access_token(config, team_id)
        # Only the bring-your-own path can auto-join — the legacy shared app lacks channels:join.
        # Joining is idempotent and only touches public channels the bot isn't in, so running it on
        # each discovery/refresh also picks up channels created since the last pass.
        if config.slack_access_token and config.join_public_channels and config.join_public_channels.enabled:
            join_public_channels(access_token, cache_id, authed_user)
        channels = get_channels(cache_id, access_token, authed_user, force_refresh=force_refresh)
        for ch in channels:
            if ch["id"] in ENDPOINTS:
                continue
            # Channel message tables are webhook-only: messages arrive via the realtime webhook
            # pipeline, not the polling sync, so incremental/append don't apply and full-refresh
            # would only delete data and reload nothing. Webhook is the only sync method we offer
            # (mirrors the Customer.io webhook schemas).
            schemas.append(
                SourceSchema(
                    name=ch["id"],
                    label=ch["name"],
                    supports_incremental=False,
                    supports_append=False,
                    supports_webhooks=True,
                    webhook_only=True,
                    incremental_fields=[],
                )
            )

        return schemas

    def validate_credentials(
        self, config: SlackSourceConfig, team_id: int, schema_name: Optional[str] = None, api_version: str | None = None
    ) -> tuple[bool, str | None]:
        try:
            access_token, _authed_user, _cache_id = self._resolve_access_token(config, team_id)

            if validate_slack_credentials(access_token):
                return True, None

            return False, "Invalid Slack credentials"
        except Exception as e:
            return False, f"Failed to validate Slack credentials: {str(e)}"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SlackResumeConfig]:
        return ResumableSourceManager[SlackResumeConfig](inputs, SlackResumeConfig)

    def source_for_pipeline(
        self,
        config: SlackSourceConfig,
        resumable_source_manager: ResumableSourceManager[SlackResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        access_token, authed_user, cache_id = self._resolve_access_token(config, inputs.team_id)

        # For channel schemas, the schema name is the channel ID itself
        channel_id = inputs.schema_name if inputs.schema_name not in ENDPOINTS else None

        webhook_source_manager = self.get_webhook_source_manager(inputs)

        return slack_source(
            access_token=access_token,
            cache_id=cache_id,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
            channel_id=channel_id,
            webhook_source_manager=webhook_source_manager,
            authed_user=authed_user,
        )
