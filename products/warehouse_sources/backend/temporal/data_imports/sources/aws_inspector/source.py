from typing import cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_inspector.aws_inspector import (
    AwsInspectorResumeConfig,
    aws_inspector_source,
    validate_credentials as validate_aws_inspector_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_inspector.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_inspector.settings import (
    DEFAULT_REGION,
    ENDPOINT_DESCRIPTIONS,
    ENDPOINTS,
    ERROR_MESSAGES,
    INCREMENTAL_FIELDS,
    INSPECTOR_API_VERSION,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awsinspector import (
    AwsInspectorSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AwsInspectorSource(ResumableSource[AwsInspectorSourceConfig, AwsInspectorResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = (INSPECTOR_API_VERSION,)
    default_version = INSPECTOR_API_VERSION
    api_docs_url = "https://docs.aws.amazon.com/inspector/v2/APIReference/Welcome.html"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSINSPECTOR

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {f"AWS Inspector request failed: {code}": message for code, message in ERROR_MESSAGES.items()}

    def get_retryable_errors(self) -> set[str]:
        return {
            "AWS Inspector request failed: ThrottlingException",
            "AWS Inspector request failed: InternalServerException",
            "AWS Inspector request failed: HTTP 429",
            "AWS Inspector request failed: HTTP 5",
        }

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AwsInspectorSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(ENDPOINTS, INCREMENTAL_FIELDS, names, descriptions=ENDPOINT_DESCRIPTIONS)

    def validate_credentials(
        self,
        config: AwsInspectorSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_aws_inspector_credentials(config, schema_name, self.resolve_api_version(api_version))

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AwsInspectorResumeConfig]:
        return ResumableSourceManager(inputs, AwsInspectorResumeConfig)

    def source_for_pipeline(
        self,
        config: AwsInspectorSourceConfig,
        resumable_source_manager: ResumableSourceManager[AwsInspectorResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return aws_inspector_source(
            config=config,
            endpoint=inputs.schema_name,
            manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            last_value=inputs.db_incremental_field_last_value,
            api_version=self.resolve_api_version(inputs.api_version),
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AWSINSPECTOR,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="AWS Inspector",
            caption="""Sync Amazon Inspector findings and scan coverage into the PostHog Data warehouse.

Enable Amazon Inspector in the region you select. Grant these IAM permissions for the tables you select:
`inspector2:ListFindings`, `inspector2:ListCoverage`, and `inspector2:ListCoverageStatistics`.

Enter your access key ID and secret access key. Add a session token if you use temporary credentials.
This source reads one AWS region.""",
            iconPath="/static/services/aws_inspector.png",
            docsUrl="https://posthog.com/docs/cdp/sources/aws-inspector",
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["aws", "inspector", "security", "vulnerabilities"],
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
                        caption="Temporary credentials expire. Connect again with new credentials when the session token expires.",
                        secret=True,
                    ),
                    SourceFieldInputConfig(
                        name="region",
                        label="AWS region",
                        type=SourceFieldInputConfigType.TEXT,
                        required=True,
                        placeholder=DEFAULT_REGION,
                        secret=False,
                    ),
                ],
            ),
        )
