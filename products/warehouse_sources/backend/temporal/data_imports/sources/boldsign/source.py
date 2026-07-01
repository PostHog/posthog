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
from products.warehouse_sources.backend.temporal.data_imports.sources.boldsign.boldsign import (
    BoldSignResumeConfig,
    boldsign_source,
    validate_credentials as validate_boldsign_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.boldsign.settings import (
    BOLDSIGN_ENDPOINTS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import BoldSignSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class BoldSignSource(ResumableSource[BoldSignSourceConfig, BoldSignResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.BOLDSIGN

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.BOLD_SIGN,
            category=DataWarehouseSourceCategory.SALES,
            label="BoldSign",
            releaseStatus=ReleaseStatus.ALPHA,
            unreleasedSource=True,
            caption="""Enter your BoldSign API key to pull your eSignature documents, templates, and contacts into the PostHog Data warehouse.

Create an API key in your [BoldSign account settings](https://app.boldsign.com/settings) under **API** → **API Key**. API keys carry all scopes by default.

Pick the region your BoldSign account lives in — accounts are hosted on either the US (`api.boldsign.com`) or EU (`api-eu.boldsign.com`) host.""",
            iconPath="/static/services/boldsign.png",
            docsUrl="https://posthog.com/docs/cdp/sources/boldsign",
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
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="us",
                        options=[
                            SourceFieldSelectConfigOption(label="US", value="us"),
                            SourceFieldSelectConfigOption(label="EU", value="eu"),
                        ],
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.boldsign.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # 401/403 surface as a requests HTTPError when `_fetch_page` calls `raise_for_status()`.
            # Retrying can never satisfy a credential problem, so stop the sync. Match the stable
            # status text and base host, not the per-request path/query.
            "401 Client Error: Unauthorized for url: https://api.boldsign.com": "Your BoldSign API key is invalid or has been revoked. Create a new key in your BoldSign account settings, then reconnect.",
            "401 Client Error: Unauthorized for url: https://api-eu.boldsign.com": "Your BoldSign API key is invalid or has been revoked. Create a new key in your BoldSign account settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.boldsign.com": "Your BoldSign API key does not have permission to access this data. Check the key's permissions, then reconnect.",
            "403 Client Error: Forbidden for url: https://api-eu.boldsign.com": "Your BoldSign API key does not have permission to access this data. Check the key's permissions, then reconnect.",
        }

    def get_schemas(
        self,
        config: BoldSignSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        schemas = [
            SourceSchema(
                # BoldSign has no reliable server-side updated-since filter, so every table is
                # full refresh (no incremental / append).
                name=endpoint,
                supports_incremental=False,
                supports_append=False,
                incremental_fields=[],
                should_sync_default=BOLDSIGN_ENDPOINTS[endpoint].should_sync_default,
                detected_primary_keys=BOLDSIGN_ENDPOINTS[endpoint].primary_keys,
            )
            for endpoint in ENDPOINTS
        ]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: BoldSignSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        return validate_boldsign_credentials(config.region, config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[BoldSignResumeConfig]:
        return ResumableSourceManager[BoldSignResumeConfig](inputs, BoldSignResumeConfig)

    def source_for_pipeline(
        self,
        config: BoldSignSourceConfig,
        resumable_source_manager: ResumableSourceManager[BoldSignResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return boldsign_source(
            region=config.region,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
