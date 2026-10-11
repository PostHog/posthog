from typing import cast

from sources.ahrefs._config import AhrefsSourceConfig
from sources.ahrefs.ahrefs import (
    ahrefs_source,
    validate_credentials as validate_ahrefs_credentials,
)
from sources.ahrefs.canonical_descriptions import CANONICAL_DESCRIPTIONS
from sources.ahrefs.settings import ENDPOINTS, MAX_PAGE_ROWS, NON_RETRYABLE_ERRORS
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
class AhrefsSource(SimpleSource[AhrefsSourceConfig]):
    lists_tables_without_credentials = True
    supported_versions = ("v3",)
    default_version = "v3"
    api_docs_url = "https://docs.ahrefs.com/en/api/docs/introduction"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AHREFS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return NON_RETRYABLE_ERRORS

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AhrefsSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(
            ENDPOINTS, {}, names, descriptions={name: endpoint["description"] for name, endpoint in ENDPOINTS.items()}
        )

    def validate_credentials(
        self,
        config: AhrefsSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if not config.project_id.isascii() or not config.project_id.isdigit() or int(config.project_id) <= 0:
            return False, "Enter a positive Site Audit project ID from your Ahrefs project URL."
        return validate_ahrefs_credentials(config.api_key)

    def source_for_pipeline(self, config: AhrefsSourceConfig, inputs: SourceInputs) -> SourceResponse:
        return ahrefs_source(config.api_key, config.project_id, inputs.schema_name, inputs.team_id, inputs.job_id)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AHREFS,
            category=DataWarehouseSourceCategory.ANALYTICS,
            label="Ahrefs",
            iconPath="/static/services/ahrefs.png",
            releaseStatus=ReleaseStatus.ALPHA,
            caption=(
                "Requires an Ahrefs Lite plan or higher. "
                "Create an API key in [Account settings > API keys](https://app.ahrefs.com/account/api-keys). "
                "Syncs use your account's API units. Health scores are free. "
                "Issues and pages each cost 50 units per request. "
                f"Each sync imports the latest crawl, with a sample of up to {MAX_PAGE_ROWS} pages. "
                "Page data requires verified project ownership."
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
                        name="project_id",
                        label="Site Audit project ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="123456",
                        secret=False,
                        caption="Use the ID from https://app.ahrefs.com/site-audit/123456.",
                    ),
                ],
            ),
        )
