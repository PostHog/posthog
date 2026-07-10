from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MailgunSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.mailgun import (
    MailgunResumeConfig,
    mailgun_source,
    validate_credentials as validate_mailgun_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MailgunSource(ResumableSource[MailgunSourceConfig, MailgunResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    supported_versions = ("v3",)
    default_version = "v3"
    api_docs_url = "https://documentation.mailgun.com/"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MAILGUN

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.mailgun.net": "Mailgun authentication failed. Please check your private API key.",
            "401 Client Error: Unauthorized for url: https://api.eu.mailgun.net": "Mailgun authentication failed. Please check your private API key and that the EU region is correct for your account.",
            "403 Client Error: Forbidden for url: https://api.mailgun.net": "Mailgun denied access. Please check that your API key has the required permissions.",
            "403 Client Error: Forbidden for url: https://api.eu.mailgun.net": "Mailgun denied access. Please check that your API key has the required permissions.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MAILGUN,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Mailgun",
            caption="""Enter your Mailgun private API key to pull your Mailgun data into the PostHog Data warehouse.

You can find your private API key in the [Mailgun dashboard](https://app.mailgun.com/settings/api_security) under **Settings → API security**. Pick the region that matches where your Mailgun account is hosted.

Note: Mailgun only retains events for a limited period (1 day on free plans, up to 30 days on paid plans), so the initial events sync is bounded by your plan's retention.""",
            iconPath="/static/services/mailgun.png",
            docsUrl="https://posthog.com/docs/cdp/sources/mailgun",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="Private API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="us",
                        options=[
                            SourceFieldSelectConfigOption(label="US (api.mailgun.net)", value="us"),
                            SourceFieldSelectConfigOption(label="EU (api.eu.mailgun.net)", value="eu"),
                        ],
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.mailgun.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: MailgunSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=endpoint in INCREMENTAL_FIELDS,
                supports_append=endpoint in INCREMENTAL_FIELDS,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
            )
            for endpoint in ENDPOINTS
        ]

        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]

        return schemas

    def validate_credentials(
        self, config: MailgunSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_mailgun_credentials(config.api_key, config.region):
            return True, None

        return False, "Invalid Mailgun API key or region"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[MailgunResumeConfig]:
        return ResumableSourceManager[MailgunResumeConfig](inputs, MailgunResumeConfig)

    def source_for_pipeline(
        self,
        config: MailgunSourceConfig,
        resumable_source_manager: ResumableSourceManager[MailgunResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return mailgun_source(
            api_key=config.api_key,
            region=config.region,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field=inputs.incremental_field,
        )
