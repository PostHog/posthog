from typing import Optional, cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.demodesk.demodesk import (
    DemodeskResumeConfig,
    demodesk_source,
    validate_credentials as validate_demodesk_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.demodesk.settings import (
    DEMODESK_ENDPOINTS,
    ENDPOINTS,
    INCREMENTAL_FIELDS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.demodesk import (
    DemodeskSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class DemodeskSource(ResumableSource[DemodeskSourceConfig, DemodeskResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog, safe for public docs

    # Pinned to v2 (the vendor's recommended surface). Meeting endpoints still ride the legacy v1
    # surface, which Demodesk keeps alive until those endpoints are migrated to v2.
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://demodesk.com/api/docs/index.html"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.DEMODESK

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Demodesk rejected the API key. Generate a new key in your Demodesk integration settings and reconnect.",
            "403 Client Error: Forbidden for url": "The API key does not have access to this data. Use a company admin's API key to sync team-wide data.",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.demodesk.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: DemodeskSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: DemodeskSourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        # requests encodes headers as latin-1, so a key with a non-ASCII character (for example an
        # invisible one pasted from another app) would surface a raw UnicodeEncodeError.
        if not config.api_key.isascii():
            return (
                False,
                "The API key contains an unsupported character (for example an invisible one pasted "
                "from another app). Retype it by hand and try again.",
            )
        return validate_demodesk_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[DemodeskResumeConfig]:
        return ResumableSourceManager[DemodeskResumeConfig](inputs, DemodeskResumeConfig)

    def source_for_pipeline(
        self,
        config: DemodeskSourceConfig,
        resumable_source_manager: ResumableSourceManager[DemodeskResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        endpoint_config = DEMODESK_ENDPOINTS.get(inputs.schema_name)
        if endpoint_config is None:
            raise ValueError(f"Demodesk source has no schema named '{inputs.schema_name}'")

        resource = demodesk_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
            incremental_field_name=inputs.incremental_field,
        )

        response = SourceResponse(
            name=endpoint_config.name,
            items=lambda: resource,
            primary_keys=endpoint_config.primary_keys,
            column_hints=resource.column_hints,
            sort_mode=endpoint_config.sort_mode,
        )
        if endpoint_config.partition_key:
            response.partition_count = 1
            response.partition_size = 1
            response.partition_mode = "datetime"
            response.partition_format = "week"
            response.partition_keys = [endpoint_config.partition_key]
        return response

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.DEMODESK,
            category=DataWarehouseSourceCategory.SALES,
            label="Demodesk",
            caption="Enter your Demodesk API key. Admins can generate one in Demodesk under integration settings, in the Demodesk API section. Use a company admin's key to sync team-wide meetings and recordings. A regular user's key only syncs what that user can see.",
            docsUrl="https://posthog.com/docs/cdp/sources/demodesk",
            iconPath="/static/services/demodesk.png",
            releaseStatus=ReleaseStatus.ALPHA,
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
