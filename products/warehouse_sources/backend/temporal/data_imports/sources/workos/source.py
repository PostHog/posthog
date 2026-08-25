from typing import TYPE_CHECKING, Optional, cast

from products.warehouse_sources.backend.temporal.data_imports.sources.common.webhook_s3 import WebhookSourceManager

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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.workos import WorkOSSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.workos.settings import (
    ALL_WEBHOOK_EVENTS,
    ENDPOINTS,
    WEBHOOK_SCHEMA_NAMES,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.workos.workos import (
    WorkOSResumeConfig,
    create_webhook as create_workos_webhook,
    delete_webhook as delete_workos_webhook,
    get_webhook_info as get_workos_webhook_info,
    sync_webhook_events as sync_workos_webhook_events,
    validate_credentials as validate_workos_credentials,
    workos_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class WorkOSSource(
    ResumableSource[WorkOSSourceConfig, WorkOSResumeConfig],
    WebhookSource[WorkOSSourceConfig],
):
    api_docs_url = "https://workos.com/docs/reference"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.WORKOS

    @property
    def webhook_template(self) -> Optional["HogFunctionTemplateDC"]:
        from products.warehouse_sources.backend.temporal.data_imports.sources.workos.webhook_template import template

        return template

    @property
    def webhook_resource_map(self) -> dict[str, str]:
        return {name: name for name in WEBHOOK_SCHEMA_NAMES}

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.WORK_OS,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="WorkOS",
            releaseStatus=ReleaseStatus.BETA,
            caption="""Enter your WorkOS API key to sync your WorkOS data into the PostHog Data warehouse.

You can find your API key in the [WorkOS Dashboard](https://dashboard.workos.com/) under **API Keys**.

The key starts with `sk_`.
""",
            iconPath="/static/services/workos.png",
            docsUrl="https://posthog.com/docs/cdp/sources/workos",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="sk_...",
                        secret=True,
                    ),
                ],
            ),
            webhookSetupCaption="""PostHog can create the WorkOS webhook automatically. To set it up manually:

1. Open **Webhooks** in the WorkOS Dashboard.
2. Create an endpoint and paste the webhook URL shown below.
3. Select the events for the tables you sync.
4. Copy the endpoint's signing secret into the field below.
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.workos.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: WorkOSSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # WorkOS list endpoints expose no server-side timestamp filter, so a polled sync is
        # always a full refresh. The tables in WEBHOOK_SCHEMA_NAMES can switch to webhook sync
        # after the initial backfill.
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
            "401 Client Error: Unauthorized for url: https://api.workos.com": "Your WorkOS API key is invalid or has been revoked. Please update the key in your WorkOS dashboard and reconnect.",
            # A WorkOS API key can make any request in its own environment, so a 403 is about the
            # account rather than the key's access: the key belongs to another environment, or the
            # product behind the endpoint is not enabled.
            "403 Client Error: Forbidden for url: https://api.workos.com": "WorkOS refused access to one of the endpoints being synced. Check that the API key comes from the WorkOS environment that holds this data, and that the product behind the table is enabled for your account. Then reconnect the source.",
            # WorkOS returns 422 for a syntactically valid list request it can't fulfil for this
            # account — e.g. the Directory Sync endpoints (directory_users/directory_groups) when
            # Directory Sync isn't provisioned. It's deterministic, so retrying never resolves it.
            "422 Client Error: Unprocessable Entity for url: https://api.workos.com": "WorkOS could not process the request for one of the endpoints being synced. This usually means the data isn't available for your WorkOS account (for example, Directory Sync isn't configured). Please check your WorkOS configuration and the endpoints you're syncing, then reconnect.",
        }

    def validate_credentials(
        self,
        config: WorkOSSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_workos_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[WorkOSResumeConfig]:
        return ResumableSourceManager[WorkOSResumeConfig](inputs, WorkOSResumeConfig)

    def get_webhook_source_manager(self, inputs: SourceInputs) -> WebhookSourceManager:
        return WebhookSourceManager(inputs, inputs.logger)

    def create_webhook(
        self, config: WorkOSSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> WebhookCreationResult:
        return create_workos_webhook(config.api_key, webhook_url, list(ALL_WEBHOOK_EVENTS))

    def get_desired_webhook_events(
        self, config: WorkOSSourceConfig, eligible_schema_names: list[str]
    ) -> list[str] | None:
        return list(ALL_WEBHOOK_EVENTS)

    def sync_webhook_events(
        self,
        config: WorkOSSourceConfig,
        webhook_url: str,
        team_id: int,
        eligible_schema_names: list[str],
        api_version: str | None = None,
    ) -> WebhookSyncResult:
        desired_events = self.get_desired_webhook_events(config, eligible_schema_names) or []
        return sync_workos_webhook_events(config.api_key, webhook_url, desired_events)

    def get_external_webhook_info(
        self, config: WorkOSSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> ExternalWebhookInfo:
        return get_workos_webhook_info(config.api_key, webhook_url)

    def delete_webhook(
        self, config: WorkOSSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> WebhookDeletionResult:
        return delete_workos_webhook(config.api_key, webhook_url)

    def source_for_pipeline(
        self,
        config: WorkOSSourceConfig,
        resumable_source_manager: ResumableSourceManager[WorkOSResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return workos_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            webhook_source_manager=self.get_webhook_source_manager(inputs),
        )
