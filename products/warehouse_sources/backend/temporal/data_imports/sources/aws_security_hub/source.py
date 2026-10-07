from typing import cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_security_hub.aws_security_hub import (
    AwsSecurityHubResumeConfig,
    aws_security_hub_source,
    probe_endpoint_permissions,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_security_hub.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_security_hub.settings import (
    API_DOCS_URL,
    ENDPOINT_DESCRIPTIONS,
    ENDPOINTS,
    ERROR_MESSAGES,
    INCREMENTAL_FIELDS,
    SECURITY_HUB_API_VERSION,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awssecurityhub import (
    AwsSecurityHubSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AwsSecurityHubSource(ResumableSource[AwsSecurityHubSourceConfig, AwsSecurityHubResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = (SECURITY_HUB_API_VERSION,)
    default_version = SECURITY_HUB_API_VERSION
    api_docs_url = API_DOCS_URL

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSSECURITYHUB

    @property
    def connection_host_fields(self) -> list[str]:
        return ["region"]

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {f"AWS Security Hub request failed: {code}": message for code, message in ERROR_MESSAGES.items()}

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AwsSecurityHubSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(
            ENDPOINTS, INCREMENTAL_FIELDS, names, merge_only={"findings"}, descriptions=ENDPOINT_DESCRIPTIONS
        )

    def validate_credentials(
        self,
        config: AwsSecurityHubSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config, self.resolve_api_version(api_version), schema_name)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AwsSecurityHubResumeConfig]:
        return ResumableSourceManager(inputs, AwsSecurityHubResumeConfig)

    def get_endpoint_permissions(
        self,
        config: AwsSecurityHubSourceConfig,
        team_id: int,
        endpoints: list[str],
        api_version: str | None = None,
    ) -> dict[str, str | None]:
        return probe_endpoint_permissions(config, self.resolve_api_version(api_version), endpoints)

    def source_for_pipeline(
        self,
        config: AwsSecurityHubSourceConfig,
        resumable_source_manager: ResumableSourceManager[AwsSecurityHubResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return aws_security_hub_source(
            config=config,
            endpoint=inputs.schema_name,
            api_version=self.resolve_api_version(inputs.api_version),
            manager=resumable_source_manager,
            should_use_incremental_field=inputs.should_use_incremental_field,
            db_incremental_field_last_value=inputs.db_incremental_field_last_value,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AWSSECURITYHUB,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="AWS Security Hub",
            caption="""Sync Security Hub CSPM findings, standards, and custom insights from the configured AWS region.

Grant `securityhub:GetFindings`, `securityhub:DescribeStandards`, `securityhub:GetEnabledStandards`, and `securityhub:GetInsights` to the IAM user or role.
Enter its access key ID and secret access key. Add a session token for temporary credentials.
Enable Security Hub CSPM in the selected region.
If you select an aggregation region, AWS can also return findings from linked regions.""",
            iconPath="/static/services/aws_security_hub.png",
            docsUrl="https://posthog.com/docs/cdp/sources/aws-security-hub",
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
                        name="aws_session_token",
                        label="AWS session token",
                        type=SourceFieldInputConfigType.PASSWORD,
                        required=False,
                        placeholder="Only needed for temporary credentials",
                        caption="Temporary credentials expire. Reconnect with new credentials when the session token expires.",
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
