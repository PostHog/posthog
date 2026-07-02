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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MailjetSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mailjet.mailjet import (
    MailjetResumeConfig,
    mailjet_source,
    validate_credentials as validate_mailjet_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailjet.settings import MAILJET_ENDPOINTS
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MailJetSource(ResumableSource[MailjetSourceConfig, MailjetResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MAILJET

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MAILJET,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Mailjet",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Mailjet API key and secret key to pull your Mailjet data into the PostHog Data warehouse.

You can find your API key and secret key in your [Mailjet API key management page](https://app.mailjet.com/account/apikeys).
""",
            iconPath="/static/services/mailjet.png",
            docsUrl="https://posthog.com/docs/cdp/sources/mailjet",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Mailjet API key",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="secret_key",
                        label="Secret key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Mailjet secret key",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.mailjet.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: MailjetSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # List resources have no reliable server-side time filter (full refresh only).
        # The statistics endpoints support Mailjet's FromTS window, so they sync incrementally.
        # Within-sync resumption is handled by ResumableSource for all endpoints.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=bool(endpoint_config.from_ts_field),
                supports_append=bool(endpoint_config.from_ts_field),
                incremental_fields=endpoint_config.incremental_fields,
            )
            for endpoint, endpoint_config in MAILJET_ENDPOINTS.items()
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: MailjetSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_mailjet_credentials(config.api_key, config.secret_key):
            return True, None

        return False, "Invalid Mailjet API key or secret key"

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.mailjet.com": (
                "Your Mailjet API key or secret key is invalid. Please check your credentials in the Mailjet "
                "API key management page and reconnect."
            ),
        }

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[MailjetResumeConfig]:
        return ResumableSourceManager[MailjetResumeConfig](inputs, MailjetResumeConfig)

    def source_for_pipeline(
        self,
        config: MailjetSourceConfig,
        resumable_source_manager: ResumableSourceManager[MailjetResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return mailjet_source(
            api_key=config.api_key,
            secret_key=config.secret_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
