from typing import cast

from products.warehouse_sources.backend.facade.source_config import (
    DataWarehouseSourceCategory,
    ReleaseStatus,
    SourceConfig,
    SourceFieldInputConfig,
    SourceFieldInputConfigType,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_savings_plans.aws_savings_plans import (
    AwsSavingsPlansResumeConfig,
    aws_savings_plans_source,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_savings_plans.canonical_descriptions import (
    CANONICAL_DESCRIPTIONS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.aws_savings_plans.settings import (
    ENDPOINT_DESCRIPTIONS,
    ENDPOINTS,
    ERROR_MESSAGES,
    INCREMENTAL_FIELDS,
    SAVINGS_PLANS_API_VERSION,
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
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.awssavingsplans import (
    AwsSavingsPlansSourceConfig,
)
from products.warehouse_sources.backend.types import ExternalDataSourceType


@SourceRegistry.register
class AwsSavingsPlansSource(ResumableSource[AwsSavingsPlansSourceConfig, AwsSavingsPlansResumeConfig]):
    lists_tables_without_credentials = True
    supported_versions = (SAVINGS_PLANS_API_VERSION,)
    default_version = SAVINGS_PLANS_API_VERSION
    api_docs_url = "https://docs.aws.amazon.com/savingsplans/latest/APIReference/Welcome.html"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSSAVINGSPLANS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {f"AWS Savings Plans request failed: {code}": message for code, message in ERROR_MESSAGES.items()}

    def get_canonical_descriptions(self) -> CanonicalDescriptions:
        return CANONICAL_DESCRIPTIONS

    def get_schemas(
        self,
        config: AwsSavingsPlansSourceConfig,
        team_id: int,
        with_counts: bool = False,
        names: list[str] | None = None,
        force_refresh: bool = False,
        api_version: str | None = None,
    ) -> list[SourceSchema]:
        return build_endpoint_schemas(
            ENDPOINTS, INCREMENTAL_FIELDS, names, descriptions=ENDPOINT_DESCRIPTIONS, merge_only=INCREMENTAL_FIELDS
        )

    def validate_credentials(
        self,
        config: AwsSavingsPlansSourceConfig,
        team_id: int,
        schema_name: str | None = None,
        api_version: str | None = None,
    ) -> tuple[bool, str | None]:
        return validate_credentials(config, schema_name, self.resolve_api_version(api_version))

    def get_resumable_source_manager(self, inputs: SourceInputs) -> ResumableSourceManager[AwsSavingsPlansResumeConfig]:
        return ResumableSourceManager(inputs, AwsSavingsPlansResumeConfig)

    def source_for_pipeline(
        self,
        config: AwsSavingsPlansSourceConfig,
        resumable_source_manager: ResumableSourceManager[AwsSavingsPlansResumeConfig],
        inputs: SourceInputs,
    ) -> SourceResponse:
        return aws_savings_plans_source(
            config,
            inputs.schema_name,
            resumable_source_manager,
            inputs.should_use_incremental_field,
            inputs.db_incremental_field_last_value,
            self.resolve_api_version(inputs.api_version),
        )

    @property
    def get_source_config(self) -> SourceConfig:
        return SourceConfig(
            name=self.source_type,
            category=DataWarehouseSourceCategory.FINANCE___ACCOUNTING,
            label="AWS Savings Plans",
            caption=(
                "Sync Savings Plans, commitment use, and coverage into the PostHog Data warehouse. "
                "Grant `savingsplans:DescribeSavingsPlans` for plan inventory. "
                "Grant `ce:GetSavingsPlansUtilization` for daily utilization. "
                "Grant `ce:GetSavingsPlansUtilizationDetails` for utilization details. "
                "Grant `ce:GetSavingsPlansCoverage` for daily coverage. "
                "Enable Cost Explorer for the metric tables. AWS charges for Cost Explorer requests. "
                "Daily utilization details require at least one request per day. "
                "This source uses the global endpoints in the standard AWS partition. "
                "Metric imports cover up to 365 days and read the previous seven days again during incremental syncs."
            ),
            iconPath="/static/services/aws_savings_plans.png",
            docsUrl=self.api_docs_url,
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
                        placeholder="Only for temporary credentials",
                        secret=True,
                        caption="Temporary credentials expire. Connect again with valid credentials when they expire.",
                    ),
                    SourceFieldInputConfig(
                        name="start_date",
                        label="Start date",
                        type=SourceFieldInputConfigType.TEXT,
                        required=False,
                        placeholder="YYYY-MM-DD",
                        secret=False,
                        caption="Optional. Imports up to 365 days of metrics when empty. AWS requires the end date before today.",
                    ),
                ],
            ),
        )
