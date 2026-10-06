from typing import cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_iam_access_analyzer.aws_iam_access_analyzer import (
    AwsIamAccessAnalyzerResumeConfig,
    aws_iam_access_analyzer_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_iam_access_analyzer.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_iam_access_analyzer.settings import (
    API_DOCS_URL,
    API_VERSION,
    DEFAULT_REGION,
    ENDPOINTS,
    ERROR_MESSAGES,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awsiamaccessanalyzer import (
    AwsIamAccessAnalyzerSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AwsIamAccessAnalyzerSource(ResumableSource[AwsIamAccessAnalyzerSourceConfig, AwsIamAccessAnalyzerResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = (API_VERSION,)
    default_version = API_VERSION
    api_docs_url = API_DOCS_URL

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSIAMACCESSANALYZER

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {f"AWS IAM Access Analyzer request failed: {code}": message for code, message in ERROR_MESSAGES.items()}

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AwsIamAccessAnalyzerSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(
            ENDPOINTS, {}, names, descriptions={name: endpoint.description for name, endpoint in ENDPOINTS.items()}
        )

    def validate_credentials(
        self,
        config: AwsIamAccessAnalyzerSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config, schema_name, self.resolve_api_version(api_version))

    def get_endpoint_permissions(
        self,
        config: AwsIamAccessAnalyzerSourceConfig,
        team_id: int,
        endpoints: list[str],
        api_version: str | None = None,
    ) -> dict[str, str | None]:
        return {
            endpoint: validate_credentials(config, endpoint, self.resolve_api_version(api_version))[1]
            for endpoint in endpoints
        }

    def get_resumable_source_manager(
        self, inputs: SourceInputs
    ) -> ResumableSourceManager[AwsIamAccessAnalyzerResumeConfig]:
        return ResumableSourceManager(inputs, AwsIamAccessAnalyzerResumeConfig)

    def source_for_pipeline(
        self,
        config: AwsIamAccessAnalyzerSourceConfig,
        resumable_source_manager: ResumableSourceManager[AwsIamAccessAnalyzerResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return aws_iam_access_analyzer_source(
            config, inputs.schema_name, resumable_source_manager, self.resolve_api_version(inputs.api_version)
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AWSIAMACCESSANALYZER,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="AWS IAM Access Analyzer",
            caption="""Sync access analyzers, findings, and archive rules from one AWS region.

Grant `access-analyzer:ListAnalyzers`, `access-analyzer:ListFindings`, and `access-analyzer:ListArchiveRules` for the tables you select.
Enter an access key ID and secret access key. Add a session token for temporary credentials.
Temporary credentials expire, so update them before later syncs.

All tables use full refresh. The API does not support a date-range filter for findings.""",
            iconPath="/static/services/aws_iam_access_analyzer.png",
            docsUrl=API_DOCS_URL,
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["aws", "iam", "access analyzer", "security"],
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
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="region",
                        label="AWS region",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        caption="Leave this blank to use us-east-1.",
                        placeholder=DEFAULT_REGION,
                        secret=False,
                    ),
                ],
            ),
        )
