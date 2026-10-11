from typing import cast

from sources.astronomer._config import AstronomerSourceConfig
from sources.astronomer.astronomer import AstronomerResumeConfig, astronomer_source, validate_credentials
from sources.astronomer.canonical_descriptions import CANONICAL_DESCRIPTIONS
from sources.astronomer.settings import ACCESS_ERROR, AUTH_ERROR, ENDPOINTS
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
