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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import InvoicedSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.invoiced.invoiced import (
    InvoicedResumeConfig,
    invoiced_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.invoiced.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    INVOICED_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class InvoicedSource(ResumableSource[InvoicedSourceConfig, InvoicedResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.INVOICED

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.INVOICED,
            category=DataWarehouseSourceCategory.PAYMENTS___BILLING,
            label="Invoiced",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Invoiced API key to pull your accounts receivable and billing data into the PostHog Data warehouse.

You can create an API key under **Settings → Developers → API Keys** in [Invoiced](https://www.invoiced.com). The key grants read access to your customers, invoices, payments, credit notes, estimates, subscriptions, and billing catalog.
""",
            iconPath="/static/services/invoiced.png",
            docsUrl="https://posthog.com/docs/cdp/sources/invoiced",
            keywords=["billing", "invoicing", "accounts receivable"],
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
            unreleasedSource=True,
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.invoiced.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.invoiced.com": "Your Invoiced API key is invalid or has been revoked. Generate a new key under Settings → Developers → API Keys, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.invoiced.com": "Your Invoiced API key does not have access to this data. Check the key's permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: InvoicedSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every list endpoint documents a server-side `updated_after` UNIX-timestamp filter, so
        # each schema advertises `updated_at` as a genuine incremental cursor.
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=True,
                supports_append=True,
                incremental_fields=INCREMENTAL_FIELDS[endpoint],
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: InvoicedSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # Invoiced API keys are account-wide, so a single probe validates access to every schema.
        return validate_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[InvoicedResumeConfig]:
        return ResumableSourceManager[InvoicedResumeConfig](inputs, InvoicedResumeConfig)

    def source_for_pipeline(
        self,
        config: InvoicedSourceConfig,
        resumable_source_manager: ResumableSourceManager[InvoicedResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in INVOICED_ENDPOINTS:
            raise ValueError(f"Unknown Invoiced schema '{inputs.schema_name}'")

        return invoiced_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
