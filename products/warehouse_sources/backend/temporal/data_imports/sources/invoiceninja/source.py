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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import InvoiceninjaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.invoiceninja.invoiceninja import (
    HOST_NOT_ALLOWED_ERROR,
    HTTP_NOT_ALLOWED_ERROR,
    InvoiceNinjaResumeConfig,
    invoiceninja_source,
    validate_credentials as validate_invoiceninja_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.invoiceninja.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    INVOICENINJA_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class InvoiceninjaSource(ResumableSource[InvoiceninjaSourceConfig, InvoiceNinjaResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.INVOICENINJA

    @property
    def connection_host_fields(self) -> list[str]:
        # `base_url` is where the stored API token is sent; retargeting it must re-require the token.
        return ["base_url"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Invalid Invoice Ninja API token. Generate a new token in Settings > Account Management > Integrations > API tokens and reconnect.",
            "403 Client Error": "Your Invoice Ninja API token is invalid or lacks permission for this data. Check the token and try again.",
            HOST_NOT_ALLOWED_ERROR: "The Invoice Ninja API URL is not allowed. Please use a publicly reachable host.",
            HTTP_NOT_ALLOWED_ERROR: "The Invoice Ninja API URL must use HTTPS. Please update the API URL to use https://.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.invoiceninja.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: InvoiceninjaSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                name=endpoint,
                supports_incremental=bool(INCREMENTAL_FIELDS.get(endpoint)),
                supports_append=bool(INCREMENTAL_FIELDS.get(endpoint)),
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=INVOICENINJA_ENDPOINTS[endpoint].should_sync_default,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: InvoiceninjaSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_invoiceninja_credentials(config.base_url, config.api_token, schema_name, team_id)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[InvoiceNinjaResumeConfig]:
        return ResumableSourceManager[InvoiceNinjaResumeConfig](inputs, InvoiceNinjaResumeConfig)

    def source_for_pipeline(
        self,
        config: InvoiceninjaSourceConfig,
        resumable_source_manager: ResumableSourceManager[InvoiceNinjaResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return invoiceninja_source(
            base_url=config.base_url,
            api_token=config.api_token,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
            team_id=inputs.team_id,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.INVOICENINJA,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Invoice Ninja",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            keywords=["invoice ninja", "invoicing", "billing"],
            caption="""Enter your Invoice Ninja API token to pull your invoicing data into the PostHog Data warehouse.

You can create an API token in Invoice Ninja under **Settings > Account Management > Integrations > API tokens**.

Self-hosted users should set the API URL to their own Invoice Ninja host (for example `https://invoices.example.com`). Leave it blank to use the hosted Invoice Ninja (`https://invoicing.co`).""",
            iconPath="/static/services/invoiceninja.png",
            docsUrl="https://posthog.com/docs/cdp/sources/invoiceninja",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="base_url",
                        label="API URL (self-hosted only)",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="https://invoicing.co",
                        secret=False,
                    ),
                ],
            ),
        )
