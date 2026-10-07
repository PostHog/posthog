from typing import cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_guardduty.aws_guardduty import (
    AwsGuarddutyResumeConfig,
    aws_guardduty_source,
    validate_credentials as validate_aws_guardduty_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_guardduty.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_guardduty.settings import (
    ENDPOINT_DESCRIPTIONS,
    ENDPOINTS,
    ERROR_MESSAGES,
    GUARDDUTY_API_VERSION,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awsguardduty import (
    AwsGuarddutySourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AwsGuarddutySource(ResumableSource[AwsGuarddutySourceConfig, AwsGuarddutyResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = (GUARDDUTY_API_VERSION,)
    default_version = GUARDDUTY_API_VERSION
    api_docs_url = "https://docs.aws.amazon.com/guardduty/latest/APIReference/Welcome.html"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSGUARDDUTY

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {f"AWS GuardDuty request failed: {code}": message for code, message in ERROR_MESSAGES.items()}

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AwsGuarddutySourceConfig,
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
        config: AwsGuarddutySourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_aws_guardduty_credentials(config, self.resolve_api_version(api_version), schema_name)

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AwsGuarddutyResumeConfig]:
        return ResumableSourceManager(inputs, AwsGuarddutyResumeConfig)

    def source_for_pipeline(
        self,
        config: AwsGuarddutySourceConfig,
        resumable_source_manager: ResumableSourceManager[AwsGuarddutyResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return aws_guardduty_source(
            config,
            inputs.schema_name,
            self.resolve_api_version(inputs.api_version),
            resumable_source_manager,
            inputs.db_incremental_field_last_value if inputs.should_use_incremental_field else None,
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=ExternalDataSourceType.AWSGUARDDUTY,
            category=DataWarehouseSourceCategory.ENGINEERING___MONITORING,
            label="AWS GuardDuty",
            iconPath="/static/services/aws_guardduty.png",
            caption=(
                "Sync GuardDuty findings, detectors, and member accounts from one AWS region. "
                "Enable GuardDuty in that region before syncing. "
                "Grant `guardduty:ListDetectors`, `guardduty:GetDetector`, `guardduty:ListFindings`, "
                "`guardduty:GetFindings`, and `guardduty:ListMembers` for all tables. "
                "The members table requires a GuardDuty administrator account. "
                "Findings use incremental sync through their update time. Other tables use full refresh."
            ),
            releaseStatus=ReleaseStatus.ALPHA,
            keywords=["aws", "guardduty", "security", "threat detection"],
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
                        caption="Temporary credentials expire. Reconnect with current credentials when the session token expires.",
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
