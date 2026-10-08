from typing import cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.acculynx.acculynx import (
    AcculynxResumeConfig,
    acculynx_source,
    appointment_range,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.acculynx.settings import (
    ENDPOINTS,
    INCREMENTAL_FIELDS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.acculynx import (
    AcculynxSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AcculynxSource(ResumableSource[AcculynxSourceConfig, AcculynxResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://apidocs.acculynx.com/changelog"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ACCULYNX

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ACCULYNX,
            category=DataWarehouseSourceCategory.CRM,
            label="AccuLynx",
            iconPath="/static/services/acculynx.png",
            docsUrl="https://posthog.com/docs/cdp/sources/acculynx",
            releaseStatus=ReleaseStatus.ALPHA,
            caption="Create an API key in [AccuLynx API settings](https://my.acculynx.com/apikeys) "
            "with a company or location administrator account. Tables use full refresh. "
            "Jobs include leads. Calendar appointments cover the date range below.",
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
                    SourceFieldInputConfig(
                        name="appointment_start_date",
                        label="Appointment start date",
                        caption="Optional. Defaults to 2000-01-01. Use YYYY-MM-DD.",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="2000-01-01",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="appointment_end_date",
                        label="Appointment end date",
                        caption="Optional. Defaults to 90 days from today. Use YYYY-MM-DD.",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="YYYY-MM-DD",
                        secret=False,
                    ),
                ],
            ),
        )

    def get_schemas(
        self,
        config: AcculynxSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            should_sync_default={"calendar_appointments": False},
            descriptions={"calendar_appointments": "Appointments within the configured date range."},
        )

    def validate_credentials(
        self,
        config: AcculynxSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if schema_name is not None and schema_name not in ENDPOINTS:
            return False, f"Unknown AccuLynx table: {schema_name}"
        try:
            dates = appointment_range(config.appointment_start_date, config.appointment_end_date)
        except ValueError as error:
            return False, str(error)
        return validate_credentials(config.api_key, self.resolve_api_version(api_version), schema_name, dates)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AcculynxResumeConfig]:
        return ResumableSourceManager(inputs, AcculynxResumeConfig)

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.acculynx.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def source_for_pipeline(
        self,
        config: AcculynxSourceConfig,
        resumable_source_manager: ResumableSourceManager[AcculynxResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        if inputs.should_use_incremental_field:
            raise ValueError("AccuLynx tables support full refresh only. Select full refresh and try again.")
        return acculynx_source(
            api_key=config.api_key,
            api_version=self.resolve_api_version(inputs.api_version),
            inputs=inputs,
            manager=resumable_source_manager,
            appointments=appointment_range(config.appointment_start_date, config.appointment_end_date),
        )

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": "Your AccuLynx API key is invalid or deactivated. Create a new key and reconnect.",
            "403 Client Error": "Your AccuLynx API key cannot access this table. Check its permissions with your administrator.",
            "AccuLynx job date window exceeds": "Too many jobs share a creation date for AccuLynx's offset limit. Contact support.",
            "AccuLynx tables support full refresh only": None,
        }
