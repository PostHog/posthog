from typing import cast

from sources.scrunch._config import ScrunchSourceConfig
from sources.scrunch.scrunch import ScrunchResumeConfig, scrunch_source, validate_credentials
from sources.scrunch.settings import API_VERSION, ENDPOINTS, INCREMENTAL_FIELDS, NON_RETRYABLE_ERRORS
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
class ScrunchSource(ResumableSource[ScrunchSourceConfig, ScrunchResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = (API_VERSION,)
    default_version = API_VERSION
    api_docs_url = "https://developers.scrunch.com/api-reference/openapi.json"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.SCRUNCH

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return NON_RETRYABLE_ERRORS

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from sources.scrunch.canonical_descriptions import CANONICAL_DESCRIPTIONS

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: ScrunchSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only={"responses"})

    def validate_credentials(
        self,
        config: ScrunchSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config.api_key)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ScrunchResumeConfig]:
        return ResumableSourceManager(inputs, ScrunchResumeConfig)

    def source_for_pipeline(
        self,
        config: ScrunchSourceConfig,
        resumable_source_manager: ResumableSourceManager[ScrunchResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return scrunch_source(config.api_key, inputs, resumable_source_manager)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.SCRUNCH,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Scrunch",
            keywords=["scrunch ai", "ai search visibility", "aeo", "geo"],
            iconPath="/static/services/scrunch.png",
            releaseStatus=ReleaseStatus.ALPHA,
            caption=(
                "An organization admin can create an API key under the organization menu > API Keys in Scrunch. "
                "Select Query scope and the brands to import. "
                "API access requires an Agency or Enterprise plan, or an override from Scrunch. "
                "Responses become available after their UTC day ends."
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
                    )
                ],
            ),
        )
