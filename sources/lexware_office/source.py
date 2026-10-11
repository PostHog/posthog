from typing import cast

from sources.lexware_office._config import LexwareOfficeSourceConfig
from sources.lexware_office.canonical_descriptions import CANONICAL_DESCRIPTIONS
from sources.lexware_office.lexware_office import (
    AUTH_ERROR,
    PERMISSION_ERROR,
    WINDOW_ERROR,
    LexwareOfficeResumeConfig,
    lexware_office_source,
    validate_credentials,
)
from sources.lexware_office.settings import ENDPOINTS
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
class LexwareOfficeSource(ResumableSource[LexwareOfficeSourceConfig, LexwareOfficeResumeConfig]):
    api_docs_url = "https://developers.lexware.io/docs/#change-log"
    lists_tables_without_credentials = True

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.LEXWAREOFFICE

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: LexwareOfficeSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(
            ENDPOINTS, {name: endpoint.incremental_fields for name, endpoint in ENDPOINTS.items()}, names
        )

    def validate_credentials(
        self,
        config: LexwareOfficeSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config.api_key, team_id, schema_name)

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error": AUTH_ERROR,
            "403 Client Error": PERMISSION_ERROR,
            WINDOW_ERROR: WINDOW_ERROR,
        }

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[LexwareOfficeResumeConfig]:
        return ResumableSourceManager(inputs, LexwareOfficeResumeConfig)

    def source_for_pipeline(
        self,
        config: LexwareOfficeSourceConfig,
        resumable_source_manager: ResumableSourceManager[LexwareOfficeResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return lexware_office_source(
            config.api_key, inputs.schema_name, inputs.team_id, inputs.job_id, resumable_source_manager
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.LEXWAREOFFICE,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="Lexware Office (formerly lexoffice), Haufe-Lexware GmbH",
            keywords=["lexoffice", "lexware", "bookkeeping"],
            docsUrl="https://posthog.com/docs/cdp/sources/lexware-office",
            iconPath="/static/services/lexware_office.png",
            caption="Create an API key in [Lexware Office](https://app.lexware.de/addons/public-api) with read access "
            "to contacts, articles, the voucher list, and the document and payment types you want to sync. "
            "Collections with 10,000 or more records cannot be imported yet.",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_key",
                        label="API key",
                        placeholder="",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        secret=True,
                    )
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )
