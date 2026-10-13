from typing import cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.referralhero import (
    ReferralHeroSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.referralhero.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.referralhero.referralhero import (
    ReferralHeroResumeConfig,
    referralhero_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.referralhero.settings import (
    API_DOCS_URL,
    AUTH_ERRORS,
    ENDPOINTS,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


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
