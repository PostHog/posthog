from typing import cast

from products.warehouse_sources.sources.aws_glue_data_catalog._config import AwsGlueDataCatalogSourceConfig
from products.warehouse_sources.sources.aws_glue_data_catalog.aws_glue_data_catalog import (
    AwsGlueDataCatalogResumeConfig,
    aws_glue_data_catalog_source,
    probe_endpoint_permissions,
    validate_credentials,
)
from products.warehouse_sources.sources.aws_glue_data_catalog.settings import (
    AWS_SESSION_ACTIONS,
    ENDPOINT_DESCRIPTIONS,
    ENDPOINTS,
    ERROR_MESSAGES,
    GLUE_API_VERSION,
)
from products.warehouse_sources.sources.sdk import (
    AWS_AUTH_NON_RETRYABLE_ERRORS,
    AWS_FLAT_STORED_SELECTS,
    AwsAuthError,
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
    aws_auth_endpoint_reasons,
    aws_auth_field,
    build_endpoint_schemas,
    detect,
    resolve_aws_credentials,
)


@SourceRegistry.register
class AwsGlueDataCatalogSource(ResumableSource[AwsGlueDataCatalogSourceConfig, AwsGlueDataCatalogResumeConfig]):
    codebase_detection = detect(
        env=("^(AWS_GLUE_DATA_CATALOG|AWSGLUEDATACATALOG)_",),
        npm=("@aws-sdk/client-glue",),
        cargo=("aws-sdk-glue",),
        go=("github.com/aws/aws-sdk-go-v2/service/glue",),
        maven=("software.amazon.awssdk:glue", "com.amazonaws:aws-java-sdk-glue"),
        rubygems=("aws-sdk-glue",),
    )

    lists_tables_without_credentials = True
    supported_versions = (GLUE_API_VERSION,)
    default_version = GLUE_API_VERSION
    api_docs_url = "https://docs.aws.amazon.com/glue/latest/webapi/API_Operations.html"

    flat_stored_selects = AWS_FLAT_STORED_SELECTS
    aws_session_actions = AWS_SESSION_ACTIONS
    credential_kind = "aws-glue-data-catalog"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSGLUEDATACATALOG

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            **AWS_AUTH_NON_RETRYABLE_ERRORS,
            **{f"AWS Glue request failed: {code}": message for code, message in ERROR_MESSAGES.items()},
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        from products.warehouse_sources.sources.aws_glue_data_catalog.canonical_descriptions import (
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
        try:
            credentials = resolve_aws_credentials(config.aws_auth, team_id, AWS_SESSION_ACTIONS)
        except AwsAuthError as error:
            return False, str(error)
        return validate_credentials(config, credentials, self.resolve_api_version(api_version), schema_name)

    def get_endpoint_permissions(
        self,
        config: AwsGlueDataCatalogSourceConfig,
        team_id: int,
        endpoints: list[str],
        api_version: str | None = None,
    ) -> dict[str, str | None]:
        try:
            credentials = resolve_aws_credentials(config.aws_auth, team_id, AWS_SESSION_ACTIONS)
        except AwsAuthError as error:
            return aws_auth_endpoint_reasons(error, endpoints)
        return probe_endpoint_permissions(config, credentials, self.resolve_api_version(api_version), endpoints)

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
            config,
            resolve_aws_credentials(config.aws_auth, inputs.team_id, AWS_SESSION_ACTIONS),
            inputs.schema_name,
            self.resolve_api_version(inputs.api_version),
            resumable_source_manager,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AWSGLUEDATACATALOG,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="AWS Glue Data Catalog",
            caption=(
                "Sync catalog metadata, job history, and crawlers from one AWS region. "
                "Grant `glue:GetDatabases`, `glue:GetTables`, `glue:GetPartitions`, and `glue:GetTableVersions` "
                "for catalog tables. "
                "Grant `glue:GetJobs`, `glue:GetJobRuns`, `glue:GetCrawlers`, and `glue:ListCrawls` for jobs and crawlers. "
                "Grant `glue:ListWorkflows` and `glue:GetWorkflowRuns` for workflow runs, "
                "and `glue:ListDataQualityResults` and `glue:ListDataQualityResultsV2` for data quality results. "
                "Grant `glue:GetTable` for column statistics, `glue:ListTableOptimizerRuns` for table optimizer runs, "
                "and `glue:ListSessions` for interactive sessions. "
                "Lake Formation permissions can also restrict catalog access. "
                "Connect with an IAM role, or enter an access key ID and secret access key. Add a session token for temporary credentials."
            ),
            iconPath="/static/services/aws_glue_data_catalog.png",
            docsUrl="https://posthog.com/docs/cdp/sources/aws-glue-data-catalog",
            releaseStatus=ReleaseStatus.BETA,
            keywords=["aws", "glue", "data catalog", "etl"],
            fields=cast(
                list[FieldType],
                [
                    aws_auth_field(),
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
