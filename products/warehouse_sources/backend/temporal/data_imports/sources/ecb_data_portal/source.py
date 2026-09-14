from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
)

from products.warehouse_sources.backend.temporal.data_imports.sources.common.base import FieldType, ResumableSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.registry import SourceRegistry
from products.warehouse_sources.backend.temporal.data_imports.sources.common.resumable import ResumableSourceManager
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import (
    SourceSchema,
    build_endpoint_schemas,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SourceInputs, SourceResponse
from products.warehouse_sources.backend.temporal.data_imports.sources.ecb_data_portal.ecb_data_portal import (
    WAF_BLOCK_MARKER,
    ECBResumeConfig,
    check_connection,
    ecb_data_portal_source,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.ecb_data_portal.settings import (
    ENDPOINT_CONFIGS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.ecbdataportal import (
    EcbDataPortalSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class EcbDataPortalSource(ResumableSource[EcbDataPortalSourceConfig, ECBResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    # SDMX 2.1 is the wire protocol, not a pinnable vendor API version — there's no version
    # path segment, header, or dated release to declare, so the framework's unversioned
    # default applies.
    api_docs_url = "https://data.ecb.europa.eu/help/api/overview"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ECBDATAPORTAL

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            WAF_BLOCK_MARKER: "ECB Data Portal blocked this request. Try again later.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.ecb_data_portal.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: EcbDataPortalSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        descriptions = {name: endpoint.description for name, endpoint in ENDPOINT_CONFIGS.items()}
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, descriptions=descriptions)

    def validate_credentials(
        self,
        config: EcbDataPortalSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        # No credentials to validate — the ECB Data Portal is a fully open, keyless API. Just
        # confirm it's reachable.
        return check_connection()

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ECBResumeConfig]:
        return ResumableSourceManager[ECBResumeConfig](inputs, ECBResumeConfig)

    def source_for_pipeline(
        self,
        config: EcbDataPortalSourceConfig,
        resumable_source_manager: ResumableSourceManager[ECBResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return ecb_data_portal_source(
            endpoint=inputs.schema_name,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.ECB_DATA_PORTAL,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="European Central Bank (ECB Data Portal)",
            caption="Import euro-area statistics from the ECB Data Portal's free, keyless public API: reference exchange rates, key interest rates, and HICP inflation. No API key or account is required.",
            iconPath="/static/services/ecb_data_portal.png",
            keywords=["ecb", "exchange rates", "eur fx", "interest rates", "inflation", "hicp"],
            fields=cast(list[FieldType], []),
            releaseStatus=ReleaseStatus.ALPHA,
        )
