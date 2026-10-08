from typing import cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_glue_data_catalog.aws_glue_data_catalog import (
    AwsGlueDataCatalogResumeConfig,
    aws_glue_data_catalog_source,
    probe_endpoint_permissions,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_glue_data_catalog.settings import (
    ENDPOINT_DESCRIPTIONS,
    ENDPOINTS,
    ERROR_MESSAGES,
    GLUE_API_VERSION,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awsgluedatacatalog import (
    AwsGlueDataCatalogSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AwsGlueDataCatalogSource(ResumableSource[AwsGlueDataCatalogSourceConfig, AwsGlueDataCatalogResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = (GLUE_API_VERSION,)
    default_version = GLUE_API_VERSION
    api_docs_url = "https://docs.aws.amazon.com/glue/latest/webapi/API_Operations.html"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSGLUEDATACATALOG

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {f"AWS Glue request failed: {code}": message for code, message in ERROR_MESSAGES.items()}

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.backend.temporal.data_imports.sources.aws_glue_data_catalog.canonical_descriptions import (
            CANONICAL_DESCRIPTIONS,
        )

        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AwsGlueDataCatalogSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, {}, names, descriptions=ENDPOINT_DESCRIPTIONS)

    def validate_credentials(
        self,
        config: AwsGlueDataCatalogSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config, self.resolve_api_version(api_version), schema_name)

    def get_endpoint_permissions(
        self,
        config: AwsGlueDataCatalogSourceConfig,
        team_id: int,
        endpoints: list[str],
        api_version: str | None = None,
    ) -> dict[str, str | None]:
        return probe_endpoint_permissions(config, self.resolve_api_version(api_version), endpoints)

    def get_resumable_source_manager(
        self, inputs: SourceInputs
    ) -> ResumableSourceManager[AwsGlueDataCatalogResumeConfig]:
        return ResumableSourceManager(inputs, AwsGlueDataCatalogResumeConfig)

    def source_for_pipeline(
        self,
        config: AwsGlueDataCatalogSourceConfig,
        resumable_source_manager: ResumableSourceManager[AwsGlueDataCatalogResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return aws_glue_data_catalog_source(
            config, inputs.schema_name, self.resolve_api_version(inputs.api_version), resumable_source_manager
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AWSGLUEDATACATALOG,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="AWS Glue Data Catalog",
            caption=(
                "Sync catalog metadata, job history, and crawlers from one AWS region. "
                "Grant `glue:GetDatabases`, `glue:GetTables`, and `glue:GetPartitions` for catalog tables. "
                "Grant `glue:GetJobs`, `glue:GetJobRuns`, and `glue:GetCrawlers` for jobs and crawlers. "
                "Lake Formation permissions can also restrict catalog access. "
                "Enter the access key ID and secret access key. Add a session token for temporary credentials."
            ),
            iconPath="/static/services/aws_glue_data_catalog.png",
            docsUrl="https://posthog.com/docs/cdp/sources/aws-glue-data-catalog",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["aws", "glue", "data catalog", "etl"],
            fields=cast(
                list[FieldType],
                [
                    SourceFieldInputConfig(
                        name="aws_access_key_id",
                        label="AWS access key ID",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="AKIA...",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="aws_secret_access_key",
                        label="AWS secret access key",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=True,
                        placeholder="",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="aws_session_token",
                        label="AWS session token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=False,
                        placeholder="Only needed for temporary credentials",
                        caption="Temporary credentials expire. Replace them before the next scheduled sync.",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="aws_region",
                        label="AWS region",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="us-east-1",
                        secret=False,
                    ),
                ],
            ),
        )
