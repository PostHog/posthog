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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import SalesflareSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.salesflare.salesflare import (
    SalesflareResumeConfig,
    check_access,
    salesflare_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.salesflare.settings import (
    ENDPOINTS,
    SALESFLARE_ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class SalesflareSource(ResumableSource[SalesflareSourceConfig, SalesflareResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SALESFLARE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SALESFLARE,
            category=DataWarehouseSourceCategory.CRM,
            label="Salesflare",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Salesflare API key to pull your CRM data into the PostHog Data warehouse.

You can create an API key under **Settings → API keys** in [Salesflare](https://app.salesflare.com/#/settings/apikeys). The key grants read access to your contacts, accounts, opportunities, pipelines, tasks, tags, and workflows.
""",
            iconPath="/static/services/salesflare.png",
            docsUrl="https://posthog.com/docs/cdp/sources/salesflare",
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
        from products.warehouse_sources.backend.temporal.data_imports.sources.salesflare.canonical_descriptions import (  # noqa: PLC0415
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.salesflare.com": "Your Salesflare API key is invalid or has been revoked. Generate a new key under Settings → API keys, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.salesflare.com": "Your Salesflare API key does not have access to this data. Check the key's permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: SalesflareSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        # Every endpoint is full refresh only — Salesflare's list endpoints expose no reliably
        # ordered server-side timestamp filter, so there is no incremental cursor to advance.
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
        self, config: SalesflareSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        # The API key is account-wide, so a single probe validates access to every schema.
        status, message = check_access(config.api_key)
        if status == 200:
            return True, None
        if status in (401, 403):
            return False, "Invalid Salesflare API key"
        return False, message or "Could not validate Salesflare API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SalesflareResumeConfig]:
        return ResumableSourceManager[SalesflareResumeConfig](inputs, SalesflareResumeConfig)

    def source_for_pipeline(
        self,
        config: SalesflareSourceConfig,
        resumable_source_manager: ResumableSourceManager[SalesflareResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.schema_name not in SALESFLARE_ENDPOINTS:
            raise ValueError(f"Unknown Salesflare schema '{inputs.schema_name}'")

        return salesflare_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
