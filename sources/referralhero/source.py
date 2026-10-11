from typing import cast

from sources.referralhero._config import ReferralHeroSourceConfig
from sources.referralhero.canonical_descriptions import CANONICAL_DESCRIPTIONS
from sources.referralhero.referralhero import ReferralHeroResumeConfig, referralhero_source, validate_credentials
from sources.referralhero.settings import API_DOCS_URL, AUTH_ERRORS, ENDPOINTS
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
class ReferralHeroSource(ResumableSource[ReferralHeroSourceConfig, ReferralHeroResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = API_DOCS_URL

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.REFERRALHERO

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return dict(AUTH_ERRORS)

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: ReferralHeroSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, {}, names)

    def validate_credentials(
        self,
        config: ReferralHeroSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config.api_token)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ReferralHeroResumeConfig]:
        return ResumableSourceManager(inputs, ReferralHeroResumeConfig)

    def source_for_pipeline(
        self,
        config: ReferralHeroSourceConfig,
        resumable_source_manager: ResumableSourceManager[ReferralHeroResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return referralhero_source(
            config.api_token, inputs.schema_name, inputs.team_id, inputs.job_id, resumable_source_manager
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.REFERRALHERO,
            category=DataWarehouseSourceCategory.MARKETING___EMAIL,
            label="ReferralHero",
            caption="Find your API token in ReferralHero under Account > API. Only active campaigns are available.",
            docsUrl=API_DOCS_URL,
            iconPath="/static/services/referralhero.png",
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="api_token",
                        label="API token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    )
                ],
            ),
            releaseStatus=ReleaseStatus.ALPHA,
        )
