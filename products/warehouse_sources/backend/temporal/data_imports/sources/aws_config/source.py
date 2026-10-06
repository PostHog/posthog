from typing import cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_config.aws_config import (
    AwsConfigResumeConfig,
    aws_config_source,
    validate_credentials as validate_aws_config_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_config.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_config.settings import (
    CONFIG_API_VERSION,
    ENDPOINT_DESCRIPTIONS,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awsconfig import (
    AwsConfigSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AwsConfigSource(ResumableSource[AwsConfigSourceConfig, AwsConfigResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = (CONFIG_API_VERSION,)
    default_version = CONFIG_API_VERSION
    api_docs_url = "https://docs.aws.amazon.com/config/latest/APIReference/Welcome.html"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSCONFIG

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {f"AWS Config request failed: {code}": message for code, message in ERROR_MESSAGES.items()}

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AwsConfigSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, {}, names, descriptions=ENDPOINT_DESCRIPTIONS)

    def validate_credentials(
        self,
        config: AwsConfigSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_aws_config_credentials(config, self.resolve_api_version(api_version), schema_name)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AwsConfigResumeConfig]:
        return ResumableSourceManager(inputs, AwsConfigResumeConfig)

    def source_for_pipeline(
        self,
        config: AwsConfigSourceConfig,
        resumable_source_manager: ResumableSourceManager[AwsConfigResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return aws_config_source(
            config, inputs.schema_name, self.resolve_api_version(inputs.api_version), resumable_source_manager
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AWSCONFIG,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="AWS Config",
            caption="""Sync resource configurations, rules, compliance status, and conformance packs from one AWS region.

Grant these IAM permissions for the tables you want to sync:
- `config:SelectResourceConfig`
- `config:DescribeConfigRules`
- `config:DescribeComplianceByConfigRule`
- `config:DescribeConformancePacks`

Enable an AWS Config recorder for resource inventory. The resources table contains current configurations and excludes deleted resources.
Add a session token if you use temporary credentials. Replace temporary credentials when they expire.""",
            iconPath="/static/services/aws_config.png",
            docsUrl="https://docs.aws.amazon.com/config/latest/APIReference/Welcome.html",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["aws", "config", "compliance", "inventory"],
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
                        placeholder="us-east-1",
                        caption="Defaults to us-east-1. Only the selected region is synced.",
                        secret=False,
                    ),
                ],
            ),
        )
