from typing import TYPE_CHECKING, Optional, cast

from products.warehouse_sources.sources.nylas._config import NylasSourceConfig
from products.warehouse_sources.sources.nylas.nylas import (
    NylasConnection,
    NylasResumeConfig,
    create_webhook as create_nylas_webhook,
    delete_webhook as delete_nylas_webhook,
    get_external_webhook_info as get_nylas_webhook_info,
    nylas_source,
    parse_grant_ids,
    sync_webhook_events as sync_nylas_webhook_events,
    validate_credentials as validate_nylas_credentials,
)
from products.warehouse_sources.sources.nylas.settings import (
    DEFAULT_EVENT_HISTORY_DAYS,
    DEFAULT_GRANT_SCOPE,
    DEFAULT_REGION,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    NYLAS_API_VERSION,
    NYLAS_ENDPOINTS,
    NYLAS_REGION_BASE_URLS,
    WEBHOOK_RESOURCE_MAP,
    WEBHOOK_TRIGGERS,
)
from products.warehouse_sources.sources.sdk import (
    CanonicalDescriptions,
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    ExternalWebhookInfo,
    FieldType,
    ReleaseStatus,
    ResumableSource,
    ResumableSourceManager,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigConverter,
    SourceFieldSelectConfigOption,
    SourceInputs,
    SourceRegistry,
    SourceResponse,
    SourceSchema,
    WebhookCreationResult,
    WebhookDeletionResult,
    WebhookSource,
    WebhookSourceManager,
    WebhookSyncResult,
    build_endpoint_schemas,
    detect,
)

if TYPE_CHECKING:
    from products.warehouse_sources.sources.sdk import HogFunctionTemplateDC


def _connection(config: NylasSourceConfig) -> NylasConnection:
    return NylasConnection(
        api_key=config.api_key,
        region=config.region,
        grant_scope=config.grant_scope,
        grant_ids=parse_grant_ids(config.grant_ids),
        include_message_bodies=config.include_message_bodies,
        event_history_days=config.event_history_days
        if config.event_history_days is not None
        else DEFAULT_EVENT_HISTORY_DAYS,
    )


@SourceRegistry.register
class NylasSource(
    ResumableSource[NylasSourceConfig, NylasResumeConfig],
    WebhookSource[NylasSourceConfig],
):
    supported_versions = (NYLAS_API_VERSION,)
    default_version = NYLAS_API_VERSION
    api_docs_url = "https://developer.nylas.com/docs/api/v3/ecc/"

    codebase_detection = detect(
        env=("^NYLAS_",),
        npm=("nylas",),
        pypi=("nylas",),
        rubygems=("nylas",),
        maven=("com.nylas.sdk:nylas",),
    )

    lists_tables_without_credentials = True

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.NYLAS

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.NYLAS,
            category=DataWarehouseSourceCategory.COMMUNICATION,
            label="Nylas",
            releaseStatus=ReleaseStatus.BETA,
            caption=(
                "Enter a Nylas API key to pull email messages, calendar events, contacts, and grants into "
                "the PostHog Data warehouse. This works for connected accounts and for Agent Accounts.\n\n"
                "You can create an API key in the [Nylas dashboard](https://dashboard-v3.nylas.com) under "
                "**API keys**. The key can read every grant in the application, so use the options "
                "below to limit which grants are synced."
            ),
            iconPath="/static/services/nylas.png",
            docsUrl="https://posthog.com/docs/cdp/sources/nylas",
            keywords=["email", "inbox", "calendar", "contacts", "agent accounts"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="nyk_v0_...",
                        secret=True,
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Data residency region",
                        required=True,
                        defaultValue=DEFAULT_REGION,
                        options=[
                            SourceFieldSelectConfigOption(label="United States", value="us"),
                            SourceFieldSelectConfigOption(label="Europe", value="eu"),
                        ],
                    ),
                    SourceFieldSelectConfig(
                        name="grant_scope",
                        sync_setting=True,
                        label="Grants to sync",
                        required=True,
                        defaultValue=DEFAULT_GRANT_SCOPE,
                        options=[
                            SourceFieldSelectConfigOption(label="All grants", value="all"),
                            SourceFieldSelectConfigOption(label="Agent Accounts only", value="agent_accounts"),
                            SourceFieldSelectConfigOption(label="Connected accounts only", value="connected_accounts"),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="grant_ids",
                        sync_setting=True,
                        label="Grant IDs",
                        caption="Optional. A comma-separated list of grant IDs. When set, only these grants are synced.",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="grant-id-1, grant-id-2",
                        secret=False,
                    ),
                    SourceFieldSelectConfig(
                        name="include_message_bodies",
                        sync_setting=True,
                        label="Sync message bodies?",
                        caption=(
                            "Choose No to store message metadata (sender, recipients, subject, snippet, dates) "
                            "without the full body."
                        ),
                        required=True,
                        defaultValue="true",
                        converter=SourceFieldSelectConfigConverter.STR_TO_BOOL,
                        options=[
                            SourceFieldSelectConfigOption(label="Yes", value="true"),
                            SourceFieldSelectConfigOption(label="No", value="false"),
                        ],
                    ),
                    SourceFieldInputConfig(
                        name="event_history_days",
                        sync_setting=True,
                        label="Calendar event history (days)",
                        caption=(
                            f"Optional. How many days of past calendar events to sync. Defaults to "
                            f"{DEFAULT_EVENT_HISTORY_DAYS}. Events up to one year ahead are always synced."
                        ),
                        type=SourceFieldInputConfigType.NUMBER,
                        required=False,
                        placeholder=str(DEFAULT_EVENT_HISTORY_DAYS),
                        secret=False,
                    ),
                ],
            ),
            webhookSetupCaption=(
                "PostHog creates the Nylas webhook for you with your API key and stores its secret.\n\n"
                "**Manual setup** (only needed if automatic creation failed):\n\n"
                "1. In the Nylas dashboard, go to **Notifications** and create a webhook\n"
                "2. Paste the webhook URL shown below into the **Webhook URL** field\n"
                "3. Select the `message.created`, `message.updated`, `event.created`, `event.updated`, "
                "`event.deleted` and `contact.updated` triggers\n"
                "4. Copy the **Webhook secret** into the field below"
            ),
            webhookFields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="signing_secret",
                        label="Webhook secret",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Nylas webhook secret",
                        secret=True,
                    ),
                ],
            ),
        )

    @property
    def webhook_template(self) -> Optional["HogFunctionTemplateDC"]:
        from products.warehouse_sources.sources.nylas.webhook_template import template

        return template

    @property
    def webhook_resource_map(self) -> dict[str, str]:
        return WEBHOOK_RESOURCE_MAP

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.sources.nylas.canonical_descriptions import CANONICAL_DESCRIPTIONS

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        errors: dict[str, str | None] = {}
        for base_url in NYLAS_REGION_BASE_URLS.values():
            errors[f"401 Client Error: Unauthorized for url: {base_url}"] = (
                "Your Nylas API key is invalid or was revoked. Create a new API key in the Nylas "
                "dashboard, check that the region matches your application, then reconnect."
            )
            errors[f"403 Client Error: Forbidden for url: {base_url}"] = (
                "Nylas rejected your API key. Check the key in the Nylas dashboard, then reconnect."
            )
        return errors

    def get_schemas(
        self,
        config: NylasSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            # These objects change after they are created (read state, new replies, edited
            # events), so an append would keep every old version as its own row.
            merge_only=tuple(INCREMENTAL_FIELDS),
            descriptions={
                name: endpoint.description for name, endpoint in NYLAS_ENDPOINTS.items() if endpoint.description
            },
            supports_webhooks=tuple(WEBHOOK_RESOURCE_MAP),
        )

    def validate_credentials(
        self,
        config: NylasSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        valid, status = validate_nylas_credentials(config.api_key, config.region)
        if valid:
            return True, None
        if status in (400, 401, 403):
            return False, (
                "Nylas rejected the API key. Check the key and that the region matches your Nylas application."
            )
        return False, "Couldn't reach Nylas to check the API key. Try again in a few minutes."

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[NylasResumeConfig]:
        return ResumableSourceManager[NylasResumeConfig](inputs, NylasResumeConfig)

    def get_webhook_source_manager(self, inputs: SourceInputs) -> WebhookSourceManager:
        return WebhookSourceManager(inputs, inputs.logger)

    def create_webhook(
        self, config: NylasSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> WebhookCreationResult:
        return create_nylas_webhook(config.api_key, config.region, webhook_url)

    def get_desired_webhook_events(
        self, config: NylasSourceConfig, eligible_schema_names: list[str]
    ) -> list[str] | None:
        # Every trigger, not only those of the selected tables: the reconcile call names one
        # table at a time, so a narrower list would unsubscribe the other tables.
        return list(WEBHOOK_TRIGGERS)

    def sync_webhook_events(
        self,
        config: NylasSourceConfig,
        webhook_url: str,
        team_id: int,
        eligible_schema_names: list[str],
        api_version: str | None = None,
    ) -> WebhookSyncResult:
        desired = self.get_desired_webhook_events(config, eligible_schema_names) or []
        return sync_nylas_webhook_events(config.api_key, config.region, webhook_url, desired)

    def get_external_webhook_info(
        self, config: NylasSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> ExternalWebhookInfo | None:
        return get_nylas_webhook_info(config.api_key, config.region, webhook_url)

    def delete_webhook(
        self, config: NylasSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> WebhookDeletionResult:
        return delete_nylas_webhook(config.api_key, config.region, webhook_url)

    def source_for_pipeline(
        self,
        config: NylasSourceConfig,
        resumable_source_manager: ResumableSourceManager[NylasResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return nylas_source(
            connection=_connection(config),
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            webhook_source_manager=self.get_webhook_source_manager(inputs),
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
