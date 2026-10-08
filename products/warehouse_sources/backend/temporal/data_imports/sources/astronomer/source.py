from typing import cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.astronomer.astronomer import (
    AstronomerResumeConfig,
    astronomer_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.astronomer.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.astronomer.settings import (
    ACCESS_ERROR,
    AUTH_ERROR,
    ENDPOINTS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.astronomer import (
    AstronomerSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AstronomerSource(ResumableSource[AstronomerSourceConfig, AstronomerResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = ("v1",)
    default_version = "v1"
    api_docs_url = "https://www.astronomer.io/docs/astro/api/versioning-and-support"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.ASTRONOMER

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {"401 Client Error": AUTH_ERROR, "403 Client Error": ACCESS_ERROR}

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AstronomerSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, {}, names)

    def validate_credentials(
        self,
        config: AstronomerSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config, schema_name)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AstronomerResumeConfig]:
        return ResumableSourceManager(inputs, AstronomerResumeConfig)

    def source_for_pipeline(
        self,
        config: AstronomerSourceConfig,
        resumable_source_manager: ResumableSourceManager[AstronomerResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return astronomer_source(config, inputs.schema_name, inputs.team_id, inputs.job_id, resumable_source_manager)

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.ASTRONOMER,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="Astronomer (Astro)",
            iconPath="/static/services/astronomer.png",
            releaseStatus=ReleaseStatus.ALPHA,
            caption=(
                "Import Astro deployments, deploy history, workspaces, and clusters. "
                "Create an organization API token in Astro under Settings > Access Management > API Tokens. "
                "Grant `organization.deployments.get`, `deployment.deploys.get`, `organization.workspaces.get`, "
                "and `organization.clusters.get` for the tables you select. "
                "Airflow DAG runs and task instances are not included."
            ),
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
                    ),
                    SourceFieldInputConfig(
                        name="organization_id",
                        label="Organization ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="",
                        secret=False,
                    ),
                ],
            ),
        )
