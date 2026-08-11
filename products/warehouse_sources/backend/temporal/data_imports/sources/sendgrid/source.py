from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.sendgrid import (
    SendGridSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sendgrid.sendgrid import (
    SendGridResumeConfig,
    get_endpoint_permissions as get_sendgrid_endpoint_permissions,
    get_endpoint_status_code,
    get_status_code,
    permission_error_for,
    sendgrid_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sendgrid.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    SENDGRID_ENDPOINTS,
    SHOULD_SYNC_DEFAULT,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SendGridSource(ResumableSource[SendGridSourceConfig, SendGridResumeConfig]):
    supported_versions = ("v3",)
    default_version = "v3"
    api_docs_url = "https://www.twilio.com/docs/sendgrid"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SENDGRID

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.sendgrid.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        # Insertion order matters: the job finalizer surfaces the message of the first matching
        # key, and the bare-host 403 key below also matches /v3/messages error text.
        return {
            "401 Client Error: Unauthorized for url: https://api.sendgrid.com": "Your SendGrid API key is invalid or expired. Please generate a new key and reconnect.",
            "403 Client Error: Forbidden for url: https://api.sendgrid.com/v3/messages": "Message activity needs SendGrid's paid additional email activity history add-on and an API key with Email Activity access. Add both in SendGrid, then resume this sync. Other SendGrid tables are not affected.",
            # Keyed on the error text, so this covers every endpoint and can't name the one scope.
            # `get_endpoint_permissions` does that per table before a sync is ever queued.
            "403 Client Error: Forbidden for url: https://api.sendgrid.com": "Your SendGrid API key cannot read this table. Add that table's read access to the key in SendGrid under Settings > API Keys, then resume this sync. Marketing lists also need an account with Marketing Campaigns.",
        }

    def get_schemas(
        self,
        config: SendGridSourceConfig,
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
            # message_activity rows mutate in place as events land (status, opens_count,
            # last_event_time), so append mode would pile up stale copies; merge on msg_id is
            # the only safe incremental mode.
            merge_only=("message_activity",),
            should_sync_default=SHOULD_SYNC_DEFAULT,
        )

    def validate_credentials(
        self,
        config: SendGridSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        # `/scopes` is readable by any genuine key, so it's the cheapest probe at source-create.
        # For a specific schema we probe its own endpoint to confirm the key has that read scope.
        endpoint = SENDGRID_ENDPOINTS.get(schema_name) if schema_name is not None else None
        status = (
            get_endpoint_status_code(config.api_key, endpoint)
            if endpoint is not None
            else get_status_code(config.api_key, "/scopes")
        )

        if status == 200:
            return True, None

        if status == 403:
            # Valid token, missing scope. Accept at source-create (users may grant scopes only for
            # the endpoints they want); reject when validating a specific schema.
            if schema_name is None:
                return True, None
            if endpoint is not None:
                return False, permission_error_for(endpoint)
            return False, "Your SendGrid API key is missing the scope required to sync this data."

        if status == 401:
            return False, "Invalid SendGrid API key"

        return False, "Could not validate SendGrid API key"

    def get_endpoint_permissions(
        self, config: SendGridSourceConfig, team_id: int, endpoints: list[str], api_version: str | None = None
    ) -> dict[str, str | None]:
        return get_sendgrid_endpoint_permissions(config.api_key, endpoints)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SendGridResumeConfig]:
        return ResumableSourceManager[SendGridResumeConfig](inputs, SendGridResumeConfig)

    def source_for_pipeline(
        self,
        config: SendGridSourceConfig,
        resumable_source_manager: ResumableSourceManager[SendGridResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return sendgrid_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SEND_GRID,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="SendGrid",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your SendGrid API key to pull your SendGrid data into the PostHog Data warehouse.

You can create an API key in your [SendGrid account settings](https://app.sendgrid.com/settings/api_keys).

Grant the following read access (Restricted Access) so the key can reach the data you want to sync:
- **Suppressions**: bounces, blocks, invalid emails, spam reports, global unsubscribes, unsubscribe groups
- **Stats**: global email statistics (daily requests, delivered, opens, clicks, bounces)
- **Marketing**: marketing lists. This also needs an account with Marketing Campaigns enabled.
- **Template Engine**: templates
- **Email Activity**: message activity. This table is off by default and also needs SendGrid's paid additional email activity history add-on.

Tables your key cannot read are flagged in the next step and left unselected.
""",
            iconPath="/static/services/sendgrid.png",
            docsUrl="https://posthog.com/docs/cdp/sources/sendgrid",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="SG....",
                        secret=True,
                    ),
                ],
            ),
        )
