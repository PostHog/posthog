from typing import Optional, cast

from sources.ortto._config import OrttoSourceConfig
from sources.ortto.ortto import (
    OrttoResumeConfig,
    ortto_source,
    validate_credentials as validate_ortto_credentials,
)
from sources.ortto.settings import ENDPOINTS, INCREMENTAL_FIELDS
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
    SourceFieldSelectConfig,
    SourceFieldSelectConfigOption,
    SourceInputs,
    SourceRegistry,
    SourceResponse,
    SourceSchema,
    build_endpoint_schemas,
)


@SourceRegistry.register
class OrttoSource(ResumableSource[OrttoSourceConfig, OrttoResumeConfig]):
    api_docs_url = "https://help.ortto.com/developer/latest/"

    lists_tables_without_credentials = True  # static endpoint catalog — safe for public docs

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ORTTO

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from sources.ortto.canonical_descriptions import CANONICAL_DESCRIPTIONS

        return CANONICAL_DESCRIPTIONS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            "401 Client Error: Unauthorized for url": "Ortto authentication failed. Please check your API key (and that it matches the selected region).",
            "403 Client Error: Forbidden for url": "Ortto denied access. Please check your API key's permissions.",
        }

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ORTTO,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="Ortto",
            caption="""Connect your Ortto account to pull your marketing data into the PostHog Data warehouse.

Create a custom API key in Ortto under Settings > API keys, and pick the region your Ortto instance lives in. Ortto's API has no updated-since filter, so all tables fully refresh on each sync.""",
            iconPath="/static/services/ortto.png",
            docsUrl="https://posthog.com/docs/cdp/sources/ortto",
            releaseStatus=ReleaseStatus.ALPHA,
            fields=cast(
                list[FieldType],
                [
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="global",
                        options=[
                            SourceFieldSelectConfigOption(label="Global", value="global"),
                            SourceFieldSelectConfigOption(label="Australia", value="au"),
                            SourceFieldSelectConfigOption(label="Europe", value="eu"),
                        ],
                    ),
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

    def get_schemas(
        self,
        config: OrttoSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names)

    def validate_credentials(
        self, config: OrttoSourceConfig, team_id: int, schema_name: Optional[str] = None, api_version: str | None = None
    ) -> tuple[bool, str | None]:
        if validate_ortto_credentials(config.region, config.api_key):
            return True, None

        return False, "Invalid Ortto credentials"

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[OrttoResumeConfig]:
        return ResumableSourceManager[OrttoResumeConfig](inputs, OrttoResumeConfig)

    def source_for_pipeline(
        self,
        config: OrttoSourceConfig,
        resumable_source_manager: ResumableSourceManager[OrttoResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return ortto_source(
            region=config.region,
            api_key=config.api_key,
            endpoint=inputs.schema_name,
            logger=inputs.logger,
            resumable_source_manager=resumable_source_manager,
        )
