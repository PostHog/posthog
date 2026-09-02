import datetime
from typing import TYPE_CHECKING, Optional, cast

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
    VersionDeprecation,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.pipedrive import (
    PipedriveSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pipedrive.pipedrive import (
    PipedriveResumeConfig,
    create_webhook as create_pipedrive_webhook,
    delete_webhook as delete_pipedrive_webhook,
    get_external_webhook_info as get_pipedrive_webhook_info,
    normalize_company_domain,
    pipedrive_source,
    validate_credentials as validate_pipedrive_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.pipedrive.settings import (
    ENDPOINTS,
    WEBHOOK_ENTITY_BY_SCHEMA,
    webhook_schema_names,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType

if TYPE_CHECKING:
    from posthog.cdp.templates.hog_function_template import HogFunctionTemplateDC


@SourceRegistry.register
class PipedriveSource(
    ResumableSource[PipedriveSourceConfig, PipedriveResumeConfig],
    WebhookSource[PipedriveSourceConfig],
):
    supported_versions = ("v1", "v2")
    default_version = "v2"
    # v1 only differs from v2 in the `activities` endpoint; the vendor deprecated the v1
    # endpoints that have v2 replacements and stops guaranteeing them after the sunset date.
    deprecated_versions = (VersionDeprecation(version="v1", sunset_at=datetime.date(2025, 12, 31)),)
    api_docs_url = "https://developers.pipedrive.com/docs/api/v1"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.PIPEDRIVE

    @property
    def webhook_template(self) -> Optional["HogFunctionTemplateDC"]:
        from products.warehouse_sources.backend.temporal.data_imports.sources.pipedrive.webhook_template import template

        return template

    @property
    def webhook_resource_map(self) -> dict[str, str]:
        return WEBHOOK_ENTITY_BY_SCHEMA

    @property
    def connection_host_fields(self) -> list[str]:
        # The stored API token is sent to `{company_domain}.pipedrive.com`; retargeting the
        # domain must re-require the token.
        return ["company_domain"]

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.PIPEDRIVE,
            category=DataWarehouseSourceCategory.CRM,
            label="Pipedrive",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Pipedrive API token to sync your Pipedrive CRM data into the PostHog Data warehouse.

You can find your personal API token in Pipedrive under **Settings > Personal preferences > API**. The token inherits your user's permissions, so make sure your user can access the data you want to sync.""",
            iconPath="/static/services/pipedrive.png",
            docsUrl="https://posthog.com/docs/cdp/sources/pipedrive",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="company_domain",
                        label="Company domain",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="mycompany",
                        caption="Enter just your Pipedrive subdomain, not a full URL. For acme.pipedrive.com, enter acme.",
                        secret=False,
                    ),
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
            webhookSetupCaption="""PostHog registers one webhook on your Pipedrive account using your API token. Pipedrive does not sign deliveries, so PostHog generates HTTP auth credentials, sets them on the webhook, and rejects any delivery that does not send them back.

**Manual setup** (only needed if automatic registration failed):

1. Go to **Tools and apps > Webhooks** in Pipedrive and click **Create new webhook**
2. Paste the webhook URL shown below into the **Endpoint URL** field
3. Set both **Event action** and **Event object** to **All**, and leave the payload version on **v2**
4. Fill in **HTTP Auth username** and **HTTP Auth password**, then enter the same two values below so PostHog can verify deliveries
5. Click **Save**

Deletions in Pipedrive are not applied to tables synced by webhook. Switch a table back to a full sync to drop deleted rows.""",
            webhookFields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="http_auth_user",
                        label="HTTP auth username",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="posthog",
                        caption="The HTTP auth username set on the Pipedrive webhook.",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="http_auth_password",
                        label="HTTP auth password",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        caption="The HTTP auth password set on the Pipedrive webhook. PostHog checks both values on every delivery.",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid Pipedrive API token. Please check your token and reconnect.",
            "403 Client Error": "Your Pipedrive user lacks permission for this data. Please check your access and reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.pipedrive.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: PipedriveSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Full refresh only: Pipedrive's v1 collections have no server-side updated_after
        # filter, and the v2 `updated_since` filter is unverified (no credentials to curl with).
        webhook_capable = webhook_schema_names(self.resolve_api_version(api_version))
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
                supports_webhooks=endpoint in webhook_capable,
            )
            for endpoint in list(ENDPOINTS)
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self,
        config: PipedriveSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        try:
            status = validate_pipedrive_credentials(config.company_domain, config.api_token)
        except ValueError as e:
            return False, str(e)

        if status == 200:
            return True, None
        # A valid token may lack scope for some endpoints; accept that at source-create
        # (schema_name is None) and only reject when validating a specific schema.
        if status == 403 and schema_name is None:
            return True, None
        if status in (401, 403):
            return False, "Invalid Pipedrive API token or insufficient permissions"
        return False, "Could not validate Pipedrive credentials"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[PipedriveResumeConfig]:
        return ResumableSourceManager[PipedriveResumeConfig](inputs, PipedriveResumeConfig)

    def get_webhook_source_manager(self, inputs: SourceInputs) -> WebhookSourceManager:
        return WebhookSourceManager(inputs, inputs.logger)

    def create_webhook(
        self, config: PipedriveSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> WebhookCreationResult:
        return create_pipedrive_webhook(config.company_domain, config.api_token, webhook_url)

    def get_external_webhook_info(
        self, config: PipedriveSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> ExternalWebhookInfo:
        return get_pipedrive_webhook_info(config.company_domain, config.api_token, webhook_url)

    def delete_webhook(
        self, config: PipedriveSourceConfig, webhook_url: str, team_id: int, api_version: str | None = None
    ) -> WebhookDeletionResult:
        return delete_pipedrive_webhook(config.company_domain, config.api_token, webhook_url)

    def source_for_pipeline(
        self,
        config: PipedriveSourceConfig,
        resumable_source_manager: ResumableSourceManager[PipedriveResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return pipedrive_source(
            company_domain=normalize_company_domain(config.company_domain),
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            api_version=self.resolve_api_version(inputs.api_version),
            resumable_source_manager=resumable_source_manager,
            webhook_source_manager=self.get_webhook_source_manager(inputs),
            db_incremental_field_last_value=None,  # every Pipedrive endpoint is full refresh
        )
