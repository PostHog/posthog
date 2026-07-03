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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import MailosaurSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.mailosaur.mailosaur import (
    MailosaurResumeConfig,
    mailosaur_source,
    validate_credentials as validate_mailosaur_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.mailosaur.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    MAILOSAUR_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class MailosaurSource(ResumableSource[MailosaurSourceConfig, MailosaurResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.MAILOSAUR

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.MAILOSAUR,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Mailosaur",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your Mailosaur API key to sync your email and SMS testing data into the PostHog Data warehouse.

You can find your API key in your [Mailosaur account settings](https://mailosaur.com/app/keys).

Use an **account-level** API key — a server-scoped key cannot list servers, so it can't enumerate the mail to sync.""",
            iconPath="/static/services/mailosaur.png",
            docsUrl="https://posthog.com/docs/cdp/sources/mailosaur",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.mailosaur.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://mailosaur.com": "Your Mailosaur API key is invalid or has been revoked. Create a new key in your Mailosaur account settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://mailosaur.com": "Your Mailosaur API key cannot access this data. Use an account-level API key, then reconnect.",
        }

    def get_schemas(
        self,
        config: MailosaurSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            has_incremental = bool(INCREMENTAL_FIELDS.get(endpoint))
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental,
                supports_append=has_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=MAILOSAUR_ENDPOINTS[endpoint].should_sync_default,
                detected_primary_keys=MAILOSAUR_ENDPOINTS[endpoint].primary_keys,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: MailosaurSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_mailosaur_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[MailosaurResumeConfig]:
        return ResumableSourceManager[MailosaurResumeConfig](inputs, MailosaurResumeConfig)

    def source_for_pipeline(
        self,
        config: MailosaurSourceConfig,
        resumable_source_manager: ResumableSourceManager[MailosaurResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return mailosaur_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
