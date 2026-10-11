from typing import cast

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
from sources.ticketmaster._config import TicketmasterSourceConfig
from sources.ticketmaster.canonical_descriptions import CANONICAL_DESCRIPTIONS
from sources.ticketmaster.settings import API_DOCS_URL, AUTH_ERRORS, ENDPOINTS, KEYWORD_ERROR, RESULT_LIMIT_ERROR
from sources.ticketmaster.ticketmaster import TicketmasterResumeConfig, ticketmaster_source, validate_credentials


@SourceRegistry.register
class TicketmasterSource(ResumableSource[TicketmasterSourceConfig, TicketmasterResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = API_DOCS_URL

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TICKETMASTER

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            **{message: message for message in AUTH_ERRORS.values()},
            "401 Client Error": AUTH_ERRORS[401],
            "403 Client Error": AUTH_ERRORS[403],
            "oauth.v2.InvalidApiKey": AUTH_ERRORS[401],
            RESULT_LIMIT_ERROR: RESULT_LIMIT_ERROR,
            KEYWORD_ERROR: KEYWORD_ERROR,
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: TicketmasterSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, {}, names)

    def validate_credentials(
        self,
        config: TicketmasterSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config, schema_name or "events", self.resolve_api_version(api_version))

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[TicketmasterResumeConfig]:
        return ResumableSourceManager(inputs, TicketmasterResumeConfig)

    def source_for_pipeline(
        self,
        config: TicketmasterSourceConfig,
        resumable_source_manager: ResumableSourceManager[TicketmasterResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return ticketmaster_source(
            config,
            inputs.schema_name,
            self.resolve_api_version(inputs.api_version),
            inputs.team_id,
            inputs.job_id,
            resumable_source_manager,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.TICKETMASTER,
            category=DataWarehouseSourceCategory.E_COMMERCE,
            label="Ticketmaster",
            iconPath="/static/services/ticketmaster.png",
            caption=(
                "Copy your API key from [My apps](https://developer.ticketmaster.com/) in the Ticketmaster Developer Portal. "
                "This source imports public Discovery API results that match your search keyword. "
                "Each table must have at most 1,000 results. Use a specific keyword to stay within this limit."
            ),
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
                        name="keyword",
                        label="Search keyword",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="Artist, event, or venue name",
                        secret=False,
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )
