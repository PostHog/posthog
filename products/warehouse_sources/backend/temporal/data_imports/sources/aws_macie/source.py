from typing import cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_macie.aws_macie import (
    AwsMacieResumeConfig,
    aws_macie_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_macie.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_macie.settings import (
    API_DOCS_URL,
    ENDPOINT_DESCRIPTIONS,
    ENDPOINTS,
    ERROR_MESSAGES,
    INCREMENTAL_FIELDS,
    MACIE_API_VERSION,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awsmacie import (
    AwsMacieSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AwsMacieSource(ResumableSource[AwsMacieSourceConfig, AwsMacieResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = (MACIE_API_VERSION,)
    default_version = MACIE_API_VERSION
    api_docs_url = API_DOCS_URL

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSMACIE

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return dict(ERROR_MESSAGES)

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AwsMacieSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, descriptions=ENDPOINT_DESCRIPTIONS)

    def validate_credentials(
        self,
        config: AwsMacieSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config, schema_name, self.resolve_api_version(api_version))

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AwsMacieResumeConfig]:
        return ResumableSourceManager(inputs, AwsMacieResumeConfig)

    def source_for_pipeline(
        self,
        config: AwsMacieSourceConfig,
        resumable_source_manager: ResumableSourceManager[AwsMacieResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return aws_macie_source(
            config,
            inputs.schema_name,
            resumable_source_manager,
            since=inputs.db_incremental_field_last_value if inputs.should_use_incremental_field else None,
            api_version=self.resolve_api_version(inputs.api_version),
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AWSMACIE,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="AWS Macie",
            caption=(
                "Sync Amazon Macie findings, S3 bucket inventory, discovery jobs, and member accounts. "
                "Enable Macie in the region you select.\n\n"
                "Grant these IAM permissions for the tables you select: "
                "`macie2:ListFindings`, `macie2:GetFindings`, `macie2:DescribeBuckets`, "
                "`macie2:ListClassificationJobs`, and `macie2:ListMembers`. "
                "Use credentials from the Macie administrator account to sync members."
            ),
            iconPath="/static/services/aws_macie.png",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["aws", "macie", "security", "s3"],
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
                        placeholder="Only for temporary credentials",
                        caption="Temporary credentials expire. Update them before scheduled syncs run.",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="region",
                        label="AWS region",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="us-east-1",
                        secret=False,
                    ),
                ],
            ),
        )
