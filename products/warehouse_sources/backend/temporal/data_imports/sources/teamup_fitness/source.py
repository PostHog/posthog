from typing import cast

from requests.exceptions import HTTPError

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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.teamupfitness import (
    TeamupFitnessSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.teamup_fitness.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.teamup_fitness.settings import (
    ENDPOINTS,
    NON_RETRYABLE_ERRORS,
    PROVIDER_ERROR,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.teamup_fitness.teamup_fitness import (
    TeamupFitnessResumeConfig,
    teamup_fitness_source,
    validate_credentials as validate_teamup_credentials,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class TeamupFitnessSource(ResumableSource[TeamupFitnessSourceConfig, TeamupFitnessResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = ("v2",)
    default_version = "v2"
    api_docs_url = "https://docs.goteamup.com/guides/migrating-from-v1"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.TEAMUPFITNESS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return NON_RETRYABLE_ERRORS

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: TeamupFitnessSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, {}, names)

    def validate_credentials(
        self,
        config: TeamupFitnessSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        if not config.provider_id.isascii() or not config.provider_id.isdecimal():
            return False, PROVIDER_ERROR
        try:
            validate_teamup_credentials(config, team_id, self.resolve_api_version(api_version))
        except HTTPError as error:
            for pattern, message in self.get_non_retryable_errors().items():
                if pattern in str(error):
                    return False, message
            raise
        return True, None

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[TeamupFitnessResumeConfig]:
        return ResumableSourceManager(inputs, TeamupFitnessResumeConfig)

    def source_for_pipeline(
        self,
        config: TeamupFitnessSourceConfig,
        resumable_source_manager: ResumableSourceManager[TeamupFitnessResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return teamup_fitness_source(
            config, inputs, resumable_source_manager, self.resolve_api_version(inputs.api_version)
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.TEAMUPFITNESS,
            category=DataWarehouseSourceCategory.CRM,
            label="TeamUp Fitness",
            iconPath="/static/services/teamup_fitness.png",
            releaseStatus=ReleaseStatus.ALPHA,
            caption=(
                "Create an M2M token in your TeamUp business dashboard. "
                "Open Settings > Integrations > API Integration > Options > Manage Applications. "
                "Enter the provider ID for your business."
            ),
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="m2m_token",
                        label="M2M token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="provider_id",
                        label="Provider ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="12345",
                        secret=False,
                    ),
                ],
            ),
        )
