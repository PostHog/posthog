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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MailerLiteSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mailerlite.mailerlite import (
    MailerLiteResumeConfig,
    mailerlite_source,
    validate_credentials as validate_mailerlite_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailerlite.settings import (
    ENDPOINTS,
    MAILERLITE_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MailerLiteSource(ResumableSource[MailerLiteSourceConfig, MailerLiteResumeConfig]):
    api_docs_url = "https://developers.mailerlite.com"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MAILERLITE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MAILER_LITE,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="MailerLite",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your MailerLite API key to pull your MailerLite data into the PostHog Data warehouse.

You can create an API key in your [MailerLite integrations settings](https://dashboard.mailerlite.com/integrations/api).""",
            iconPath="/static/services/mailerlite.png",
            docsUrl="https://posthog.com/docs/cdp/sources/mailerlite",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="Your MailerLite API key",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://connect.mailerlite.com": "Your MailerLite API key is invalid or expired. Please generate a new key and reconnect.",
            "403 Client Error: Forbidden for url: https://connect.mailerlite.com": "Your MailerLite API key does not have the required permissions. Please check the key and reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.mailerlite.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: MailerLiteSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # MailerLite exposes no server-side timestamp filter, so every endpoint is full-refresh only.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: MailerLiteSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        endpoint_config = MAILERLITE_ENDPOINTS.get(schema_name) if schema_name else None
        path = endpoint_config.path if endpoint_config else "/subscribers"
        if validate_mailerlite_credentials(config.api_key, path):
            return True, None

        return False, "Invalid MailerLite API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[MailerLiteResumeConfig]:
        return ResumableSourceManager[MailerLiteResumeConfig](inputs, MailerLiteResumeConfig)

    def source_for_pipeline(
        self,
        config: MailerLiteSourceConfig,
        resumable_source_manager: ResumableSourceManager[MailerLiteResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return mailerlite_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
