from typing import cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.arcade.arcade import (
    ERROR_MESSAGES,
    ArcadeResumeConfig,
    arcade_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.arcade.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.arcade.settings import API_DOCS_URL, ENDPOINTS
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.arcade import ArcadeSourceConfig
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class ArcadeSource(ResumableSource[ArcadeSourceConfig, ArcadeResumeConfig]):
    lists_tables_without_credentials = True
    api_docs_url = API_DOCS_URL

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ARCADE

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {message: message for message in ERROR_MESSAGES}

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: ArcadeSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        # Aggregate date filters do not identify changed rows, so each sync replaces the snapshot.
        return build_endpoint_schemas(ENDPOINTS, {}, names)

    def validate_credentials(
        self,
        config: ArcadeSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config, team_id, schema_name)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[ArcadeResumeConfig]:
        return ResumableSourceManager(inputs, ArcadeResumeConfig)

    def source_for_pipeline(
        self,
        config: ArcadeSourceConfig,
        resumable_source_manager: ResumableSourceManager[ArcadeResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return arcade_source(config, inputs.schema_name, inputs.team_id, inputs.job_id, resumable_source_manager)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ARCADE,
            category=DataWarehouseSourceCategory.SALES,
            label="Arcade",
            keywords=["interactive demo", "product demo", "demo analytics"],
            iconPath="/static/services/arcade.png",
            releaseStatus=ReleaseStatus.ALPHA,
            caption=(
                "Requires an Arcade Enterprise workspace. Create an API key in Settings > Advanced. "
                "Enable insights access for engagement data. Enable User provisioning for teams and users. "
                "All tables use full refresh. Flow engagement includes totals from your start date through each sync."
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
                        name="team_id",
                        label="Arcade team ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                        caption="Use the team ID from Arcade's GET /teams API response.",
                    ),
                    SourceFieldInputConfig(
                        name="start_date",
                        label="Engagement start date",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="YYYY-MM-DD",
                        secret=False,
                    ),
                ],
            ),
        )
