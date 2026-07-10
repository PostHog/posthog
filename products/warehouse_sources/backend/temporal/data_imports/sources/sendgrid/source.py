from typing import Optional, cast

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
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SendGridSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.sendgrid.sendgrid import (
    SendGridResumeConfig,
    get_status_code,
    sendgrid_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.sendgrid.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    SENDGRID_ENDPOINTS,
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
        return {
            "401 Client Error: Unauthorized for url: https://api.sendgrid.com": "Your SendGrid API key is invalid or expired. Please generate a new key and reconnect.",
            "403 Client Error: Forbidden for url: https://api.sendgrid.com": "Your SendGrid API key is missing a scope required to sync this data. Please grant the required read scopes and reconnect.",
        }

    def get_schemas(
        self,
        config: SendGridSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                supports_append=INCREMENTAL_FIELDS.get(endpoint, None) is not None,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in list(ENDPOINTS)
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: SendGridSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # `/scopes` is readable by any genuine key, so it's the cheapest probe at source-create.
        # For a specific schema we probe its own endpoint to confirm the key has that read scope.
        path = SENDGRID_ENDPOINTS[schema_name].path if schema_name in SENDGRID_ENDPOINTS else "/scopes"
        status = get_status_code(config.api_key, path)

        if status == 200:
            return True, None

        if status == 403:
            # Valid token, missing scope. Accept at source-create (users may grant scopes only for
            # the endpoints they want); reject when validating a specific schema.
            if schema_name is None:
                return True, None
            return False, "Your SendGrid API key is missing the scope required to sync this data."

        if status == 401:
            return False, "Invalid SendGrid API key"

        return False, "Could not validate SendGrid API key"

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
            logger=inputs.logger,
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
- **Suppressions** — bounces, blocks, invalid emails, spam reports, global unsubscribes, unsubscribe groups
- **Marketing** — marketing lists
- **Template Engine** — templates
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
