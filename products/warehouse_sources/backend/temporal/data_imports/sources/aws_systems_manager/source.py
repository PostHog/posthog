from typing import cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_systems_manager.aws_systems_manager import (
    SystemsManagerResumeConfig,
    aws_systems_manager_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_systems_manager.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_systems_manager.settings import (
    API_DOCS_URL,
    API_VERSION,
    ENDPOINTS,
    ERROR_MESSAGES,
    INCREMENTAL_FIELDS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awssystemsmanager import (
    AwsSystemsManagerSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AwsSystemsManagerSource(ResumableSource[AwsSystemsManagerSourceConfig, SystemsManagerResumeConfig]):
    lists_tables_without_credentials = True
    # SSM uses an unversioned target; the pinned botocore model serializes every request.
    supported_versions = (API_VERSION,)
    default_version = API_VERSION
    api_docs_url = API_DOCS_URL

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSSYSTEMSMANAGER

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {f"AWS Systems Manager request failed: {code}": message for code, message in ERROR_MESSAGES.items()}

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AwsSystemsManagerSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(
            ENDPOINTS,
            INCREMENTAL_FIELDS,
            names,
            descriptions={name: endpoint.description for name, endpoint in ENDPOINTS.items()},
        )

    def validate_credentials(
        self,
        config: AwsSystemsManagerSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config, self.resolve_api_version(api_version), schema_name)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[SystemsManagerResumeConfig]:
        return ResumableSourceManager(inputs, SystemsManagerResumeConfig)

    def source_for_pipeline(
        self,
        config: AwsSystemsManagerSourceConfig,
        resumable_source_manager: ResumableSourceManager[SystemsManagerResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return aws_systems_manager_source(
            config, inputs.schema_name, self.resolve_api_version(inputs.api_version), resumable_source_manager
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AWSSYSTEMSMANAGER,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="AWS Systems Manager",
            caption="""Sync fleet inventory, compliance summaries, associations, and patch baselines from one AWS region.

Grant these IAM permissions for the tables you select:
`ssm:DescribeInstanceInformation`, `ssm:GetInventory`, `ssm:ListResourceComplianceSummaries`,
`ssm:ListAssociations`, and `ssm:DescribePatchBaselines`.

Enter an access key ID and secret access key. Include a session token for temporary credentials.
All tables use full refresh. Create a separate source for each region.""",
            iconPath="/static/services/aws_systems_manager.png",
            docsUrl=API_DOCS_URL,
            keywords=["aws", "ssm"],
            releaseStatus=ReleaseStatus.ALPHA,
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
                        name="aws_region",
                        label="AWS region",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder="us-east-1",
                        secret=False,
                    ),
                    SourceFieldInputConfig(
                        name="aws_session_token",
                        label="AWS session token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=False,
                        placeholder="Only needed for temporary credentials",
                        secret=True,
                        caption="Temporary credentials expire. Update them before the next scheduled sync.",
                    ),
                ],
            ),
        )
