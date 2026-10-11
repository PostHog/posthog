from typing import cast

from sources.calendarific._config import CalendarificSourceConfig
from sources.calendarific.calendarific import CalendarificClient
from sources.calendarific.settings import ENDPOINTS, NON_RETRYABLE_ERRORS
from sources.sdk import (
    CanonicalDescriptions,
    DataWarehouseSourceCategory,
    ExternalDataSourceType,
    FieldType,
    ReleaseStatus,
    SimpleSource,
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
class CalendarificSource(SimpleSource[CalendarificSourceConfig]):
    lists_tables_without_credentials = True
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://calendarific.com/api-documentation"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.CALENDARIFIC

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return dict(NON_RETRYABLE_ERRORS)

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from sources.calendarific.canonical_descriptions import CANONICAL_DESCRIPTIONS

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: CalendarificSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, {}, names)

    def validate_credentials(
        self,
        config: CalendarificSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return CalendarificClient(config, self.resolve_api_version(api_version)).validate_credentials(
            team_id, schema_name
        )

    def source_for_pipeline(self, config: CalendarificSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return CalendarificClient(config, self.resolve_api_version(inputs.api_version)).source_response(
            inputs.schema_name, inputs.team_id, inputs.job_id
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.CALENDARIFIC,
            category=DataWarehouseSourceCategory.PRODUCTIVITY,
            label="Calendarific",
            iconPath="/static/services/calendarific.png",
            caption="Copy your API key from your [Calendarific dashboard](https://calendarific.com/account). "
            "Import holidays for one country and year. All tables use full refresh.",
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
                        name="country",
                        label="Country code",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="US",
                        secret=False,
                        caption="Enter the two-letter ISO country code for holiday imports.",
                    ),
                    SourceFieldInputConfig(
                        name="year",
                        label="Year",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="2026",
                        secret=False,
                        caption="Enter the four-digit year for holiday imports.",
                    ),
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )
