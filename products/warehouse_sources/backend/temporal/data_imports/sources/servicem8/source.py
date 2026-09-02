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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.servicem8 import (
    Servicem8SourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.servicem8.servicem8 import (
    ServiceM8ResumeConfig,
    servicem8_source,
    validate_credentials as validate_servicem8_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.servicem8.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
    PRIMARY_KEY,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class Servicem8Source(ResumableSource[Servicem8SourceConfig, ServiceM8ResumeConfig]):
    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs
    api_docs_url = "https://developer.servicem8.com/reference"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SERVICEM8

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url: https://api.servicem8.com": (
                "Your ServiceM8 API key is invalid or has been revoked. Generate a new key from "
                "Settings -> API Keys in your ServiceM8 account, then reconnect."
            ),
            "403 Client Error: Forbidden for url: https://api.servicem8.com": (
                "Your ServiceM8 API key does not have permission to access this data. Check the "
                "key's permissions in Settings -> API Keys, then reconnect."
            ),
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.servicem8.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: Servicem8SourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: Servicem8SourceConfig,
        team_id: int,
        schema_name: Optional[str] = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if validate_servicem8_credentials(config.api_key):
            return True, None

        return False, "Invalid credentials"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ServiceM8ResumeConfig]:
        return ResumableSourceManager[ServiceM8ResumeConfig](inputs, ServiceM8ResumeConfig)

    def source_for_pipeline(
        self,
        config: Servicem8SourceConfig,
        resumable_source_manager: ResumableSourceManager[ServiceM8ResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        resource = servicem8_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value
            if inputs.should_use_incremental_field
            else None,
        )
        return SourceResponse(
            name=resource.name,
            items=lambda: resource,
            primary_keys=[PRIMARY_KEY],
            column_hints=resource.column_hints,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=SchemaExternalDataSourceType.SERVICEM8,
            category=DataWarehouseSourceCategory.CRM,
            label="ServiceM8",
            caption="Enter an API key from your ServiceM8 account (Settings -> API Keys) to sync jobs, clients, staff, and job activity into the PostHog Data warehouse.",
            docsUrl="https://posthog.com/docs/cdp/sources/servicem8",
            iconPath="/static/services/servicem8.png",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["field service", "jobs", "trades"],
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
