from typing import cast

from sources.fieldpulse._config import FieldpulseSourceConfig
from sources.fieldpulse.canonical_descriptions import CANONICAL_DESCRIPTIONS
from sources.fieldpulse.fieldpulse import FieldpulseResumeConfig, fieldpulse_source, validate_credentials
from sources.fieldpulse.settings import API_DOCS_URL, AUTH_ERROR, ENDPOINTS, INCREMENTAL_FIELDS
from sources.sdk import (
    CanonicalDescriptions,
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    ReleaseStatus,
    ResumableSource,
    ResumableSourceManager,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
    SourceInputs,
    SourceRegistry,
    SourceResponse,
    SourceSchema,
    build_endpoint_schemas,
)


@SourceRegistry.register
class FieldpulseSource(ResumableSource[FieldpulseSourceConfig, FieldpulseResumeConfig]):
    lists_tables_without_credentials = True
    api_docs_url = API_DOCS_URL

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.FIELDPULSE

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": AUTH_ERROR,
            "403 Client Error": AUTH_ERROR,
            "422 Client Error": AUTH_ERROR,
            "Invalid API key": AUTH_ERROR,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: FieldpulseSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self,
        config: FieldpulseSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[FieldpulseResumeConfig]:
        return ResumableSourceManager(inputs, FieldpulseResumeConfig)

    def source_for_pipeline(
        self,
        config: FieldpulseSourceConfig,
        resumable_source_manager: ResumableSourceManager[FieldpulseResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return fieldpulse_source(
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            team_id=inputs.team_id,
            job_id=inputs.job_id,
            resumable_source_manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.FIELDPULSE,
            category=DataWarehouseSourceCategory.CRM,
            label="FieldPulse",
            caption="Contact support@fieldpulse.com to request and activate your FieldPulse API key.",
            iconPath="/static/services/fieldpulse.png",
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
                    )
                ],
            ),
        )
