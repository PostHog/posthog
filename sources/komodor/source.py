from typing import cast

from sources.komodor._config import KomodorSourceConfig
from sources.komodor.canonical_descriptions import CANONICAL_DESCRIPTIONS
from sources.komodor.komodor import KomodorResumeConfig, komodor_source, validate_credentials
from sources.komodor.settings import API_DOCS_URL, AUTH_ERRORS, ENDPOINTS
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
class KomodorSource(ResumableSource[KomodorSourceConfig, KomodorResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = API_DOCS_URL

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.KOMODOR

    @property
    def connection_host_fields(self) -> list[str]:
        return ["region"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return dict(AUTH_ERRORS)

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: KomodorSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, {}, names)

    def validate_credentials(
        self,
        config: KomodorSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config, self.resolve_api_version(api_version))

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[KomodorResumeConfig]:
        return ResumableSourceManager(inputs, KomodorResumeConfig)

    def source_for_pipeline(
        self,
        config: KomodorSourceConfig,
        resumable_source_manager: ResumableSourceManager[KomodorResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return komodor_source(
            config,
            inputs.schema_name,
            inputs.team_id,
            inputs.job_id,
            self.resolve_api_version(inputs.api_version),
            resumable_source_manager,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.KOMODOR,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Komodor",
            iconPath="/static/services/komodor.png",
            caption="Create an API key in Komodor under User settings > API Keys. Select your account's region.",
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
                    SourceFieldSelectConfig(
                        name="region",
                        label="Region",
                        required=True,
                        defaultValue="us",
                        options=[
                            SourceFieldSelectConfigOption(label="US", value="us"),
                            SourceFieldSelectConfigOption(label="EU", value="eu"),
                        ],
                    ),
                ],
            ),
        )
