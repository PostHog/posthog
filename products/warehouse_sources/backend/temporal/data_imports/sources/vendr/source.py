from typing import Optional, cast

from posthog.schema import (
    DataWarehouseSourceCategory,
    ExternalDataSourceType as SchemaExternalDataSourceType,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.vendr import VendrSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.vendr.settings import ENDPOINTS, VENDR_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.vendr.vendr import (
    VendrResumeConfig,
    validate_credentials as validate_vendr_credentials,
    vendr_source,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class VendrSource(ResumableSource[VendrSourceConfig, VendrResumeConfig]):
    # Every endpoint here is a static entry in ENDPOINTS with no I/O - safe for public docs.
    lists_tables_without_credentials = True
    # Vendr's OpenPrice API has no versioned path segment, version header, or dated release -
    # https://api.vendr.com is the only documented base.
    api_docs_url = "https://developers.vendr.com/docs/introduction"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.VENDR

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.VENDR,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Vendr (OpenPrice API)",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="Sync Vendr's OpenPrice software catalog: companies, products, product "
            "families, and categories. Access is partnership-gated - email "
            "[developers@vendr.com](mailto:developers@vendr.com) to request an API key.",
            iconPath="/static/services/vendr.png",
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

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Your Vendr API key is invalid or has been revoked. "
            "Contact developers@vendr.com to get a new key, then reconnect.",
            "403 Client Error: Forbidden for url": "Your Vendr API key does not have access to the catalog. "
            "Check your partnership terms with Vendr, then reconnect.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.vendr.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: VendrSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        schemas = build_endpoint_schemas(ENDPOINTS, {}, names)
        for schema in schemas:
            schema.detected_primary_keys = VENDR_ENDPOINTS[schema.name].primary_keys
        return schemas

    def validate_credentials(
        self,
        config: VendrSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        ok, _status_code = validate_vendr_credentials(config.api_key)
        if ok:
            return True, None
        return False, "Invalid Vendr API key"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[VendrResumeConfig]:
        return ResumableSourceManager[VendrResumeConfig](inputs, VendrResumeConfig)

    def source_for_pipeline(
        self,
        config: VendrSourceConfig,
        resumable_source_manager: ResumableSourceManager[VendrResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return vendr_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
        )
