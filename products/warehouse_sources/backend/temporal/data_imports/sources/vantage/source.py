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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs import VantageSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.vantage.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    VANTAGE_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.vantage.vantage import (
    VantageResumeConfig,
    validate_credentials as validate_vantage_credentials,
    vantage_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class VantageSource(ResumableSource[VantageSourceConfig, VantageResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog - safe for public docs
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://docs.vantage.sh/api"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.VANTAGE

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.VANTAGE,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Vantage",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="""Enter your Vantage API access token to pull your Vantage FinOps data into the PostHog Data warehouse.

Create a read-scoped access token or a service token from your [Vantage settings](https://console.vantage.sh/settings/access_tokens). Only the `read` scope is required for imports.""",
            iconPath="/static/services/vantage.png",
            docsUrl="https://posthog.com/docs/cdp/sources/vantage",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API access token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="vntg_tkn_...",
                        secret=True,
                    ),
                ],
            ),
        )

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.vantage.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            # A bad, revoked, or expired token surfaces as an HTTPError when `_fetch_page` calls
            # `raise_for_status()`. Retrying can never fix a credential problem, so stop the sync.
            "401 Client Error: Unauthorized for url: https://api.vantage.sh": "Your Vantage API access token is invalid or has been revoked. Create a new read-scoped token in your Vantage settings, then reconnect.",
            "403 Client Error: Forbidden for url: https://api.vantage.sh": "Your Vantage API access token is missing the read scope needed to sync this data. Grant the read scope in your Vantage settings, then reconnect.",
        }

    def get_schemas(
        self,
        config: VantageSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
    ) -> list[SourceSchema]:
        def _build_schema(endpoint: str) -> SourceSchema:
            endpoint_config = VANTAGE_ENDPOINTS[endpoint]
            has_incremental = len(INCREMENTAL_FIELDS.get(endpoint, [])) > 0
            return SourceSchema(
                name=endpoint,
                supports_incremental=has_incremental,
                supports_append=has_incremental,
                incremental_fields=INCREMENTAL_FIELDS.get(endpoint, []),
                should_sync_default=endpoint_config.should_sync_default,
            )

        schemas = [_build_schema(endpoint) for endpoint in ENDPOINTS]
        if names is not None:
            names_set = set(names)
            schemas = [s for s in schemas if s.name in names_set]
        return schemas

    def validate_credentials(
        self, config: VantageSourceConfig, team_id: int, schema_name: Optional[str] = None
    ) -> tuple[bool, str | None]:
        if validate_vantage_credentials(config.api_key):
            return True, None

        return False, "Invalid Vantage API access token"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[VantageResumeConfig]:
        return ResumableSourceManager[VantageResumeConfig](inputs, VantageResumeConfig)

    def source_for_pipeline(
        self,
        config: VantageSourceConfig,
        resumable_source_manager: ResumableSourceManager[VantageResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return vantage_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
