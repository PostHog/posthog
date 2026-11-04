from typing import cast

from products.warehouse_sources.sources.aws_savings_plans._config import AwsSavingsPlansSourceConfig
from products.warehouse_sources.sources.aws_savings_plans.aws_savings_plans import (
    AwsSavingsPlansResumeConfig,
    aws_savings_plans_source,
    validate_credentials,
)
from products.warehouse_sources.sources.aws_savings_plans.canonical_descriptions import CANONICAL_DESCRIPTIONS
from products.warehouse_sources.sources.aws_savings_plans.settings import (
    AWS_SESSION_ACTIONS,
    ENDPOINT_DESCRIPTIONS,
    ENDPOINTS,
    ERROR_MESSAGES,
    INCREMENTAL_FIELDS,
    SAVINGS_PLANS_API_VERSION,
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
    aws_auth_field,
    build_endpoint_schemas,
    detect,
    resolve_aws_credentials,
)


@SourceRegistry.register
class AwsSavingsPlansSource(ResumableSource[AwsSavingsPlansSourceConfig, AwsSavingsPlansResumeConfig]):
    codebase_detection = detect(
        env=("^(AWS_SAVINGS_PLANS|AWSSAVINGSPLANS)_",),
        npm=("@aws-sdk/client-savingsplans",),
        cargo=("aws-sdk-savingsplans",),
        go=("github.com/aws/aws-sdk-go-v2/service/savingsplans",),
        maven=("software.amazon.awssdk:savingsplans", "com.amazonaws:aws-java-sdk-savingsplans"),
        rubygems=("aws-sdk-savingsplans",),
    )

    lists_tables_without_credentials = True
    supported_versions = (SAVINGS_PLANS_API_VERSION,)
    default_version = SAVINGS_PLANS_API_VERSION
    api_docs_url = "https://docs.aws.amazon.com/savingsplans/latest/APIReference/Welcome.html"

    flat_stored_selects = AWS_FLAT_STORED_SELECTS
    aws_session_actions = AWS_SESSION_ACTIONS
    credential_kind = "aws-savings-plans"

    @property
    def source_type(self) -> ExternalDataSourceType:
        return ExternalDataSourceType.AWSSAVINGSPLANS

    def get_non_retryable_errors(self) -> dict[str, str | None]:
        return {
            **AWS_AUTH_NON_RETRYABLE_ERRORS,
            **{f"AWS Savings Plans request failed: {code}": message for code, message in ERROR_MESSAGES.items()},
        }

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
        try:
            credentials = resolve_aws_credentials(config.aws_auth, team_id, AWS_SESSION_ACTIONS)
        except AwsAuthError as error:
            return False, str(error)
        return validate_credentials(config, credentials, schema_name, self.resolve_api_version(api_version))

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
            resolve_aws_credentials(config.aws_auth, inputs.team_id, AWS_SESSION_ACTIONS),
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
                "Sync Savings Plans, rates, commitment use, coverage, and purchase recommendations into the PostHog Data warehouse. "
                "Grant `savingsplans:DescribeSavingsPlans` for plan inventory. "
                "Grant `ce:GetSavingsPlansUtilization` for daily utilization. "
                "Grant `ce:GetSavingsPlansUtilizationDetails` for utilization details. "
                "Grant `ce:GetSavingsPlansCoverage` for daily coverage. "
                "Grant `savingsplans:DescribeSavingsPlansOfferings` for offerings. "
                "Grant `savingsplans:DescribeSavingsPlanRates` for plan rates. "
                "Grant `ce:GetSavingsPlansPurchaseRecommendation` for purchase recommendations. "
                "Grant `ce:GetSavingsPlanPurchaseRecommendationDetails` for recommendation details. "
                "Enable Cost Explorer for the metric tables. AWS charges for Cost Explorer requests. "
                "Daily utilization details require at least one request per day. "
                "Purchase recommendations need one request for each of 57 plan type, term, payment, and lookback combinations. "
                "Recommendation details also need one request for each recommendation. "
                "This source uses the global endpoints in the standard AWS partition. "
                "Metric imports cover up to 365 days and read the previous seven days again during incremental syncs."
            ),
            iconPath="/static/services/aws_savings_plans.png",
            docsUrl=self.api_docs_url,
            releaseStatus=ReleaseStatus.BETA,
            fields=cast(
                list[FieldType],
                [
                    aws_auth_field(),
                    SourceFieldInputConfig(
                        name="start_date",
                        sync_setting=True,
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
