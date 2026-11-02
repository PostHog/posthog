from typing import Literal

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

SAVINGS_PLANS_API_VERSION = "2019-06-28"
COST_EXPLORER_API_VERSION = "2017-10-25"
SIGNING_REGION = "us-east-1"
DEFAULT_LOOKBACK_DAYS = 365
RESTATEMENT_DAYS = 7


@frozen
class SavingsPlansEndpoint:
    operation: str
    result_key: str
    primary_keys: tuple[str, ...]
    service: Literal["savingsplans", "ce"] = "ce"
    token_key: str | None = "NextToken"
    window_days: int = 92
    granularity: str | None = "DAILY"
    page_size_key: str | None = None
    page_size: int = 100
    fan_out: Literal["savings_plans", "recommendation_options", "purchase_recommendations"] | None = None
    parent_column: str | None = None

    @property
    def windowed(self) -> bool:
        return self.service == "ce" and self.fan_out is None


ENDPOINTS: dict[str, SavingsPlansEndpoint] = {
    "savings_plans": SavingsPlansEndpoint(
        operation="DescribeSavingsPlans",
        result_key="savingsPlans",
        primary_keys=("savings_plan_arn",),
        service="savingsplans",
        token_key="nextToken",
        granularity=None,
        page_size_key="maxResults",
    ),
    "utilization_daily": SavingsPlansEndpoint(
        operation="GetSavingsPlansUtilization",
        result_key="SavingsPlansUtilizationsByTime",
        primary_keys=("period_start",),
        token_key=None,
    ),
    "utilization_details_daily": SavingsPlansEndpoint(
        operation="GetSavingsPlansUtilizationDetails",
        result_key="SavingsPlansUtilizationDetails",
        primary_keys=("savings_plan_arn", "period_start"),
        window_days=1,
        granularity=None,
    ),
    "coverage_daily": SavingsPlansEndpoint(
        operation="GetSavingsPlansCoverage",
        result_key="SavingsPlansCoverages",
        primary_keys=("period_start",),
    ),
    "savings_plan_offerings": SavingsPlansEndpoint(
        operation="DescribeSavingsPlansOfferings",
        result_key="searchResults",
        primary_keys=("offering_id",),
        service="savingsplans",
        token_key="nextToken",
        granularity=None,
        page_size_key="maxResults",
        page_size=1000,
    ),
    "savings_plan_rates": SavingsPlansEndpoint(
        operation="DescribeSavingsPlanRates",
        result_key="searchResults",
        primary_keys=("savings_plan_id", "product_type", "service_code", "usage_type", "operation"),
        service="savingsplans",
        token_key="nextToken",
        granularity=None,
        page_size_key="maxResults",
        page_size=1000,
        fan_out="savings_plans",
        parent_column="savings_plan_id",
    ),
    "purchase_recommendations": SavingsPlansEndpoint(
        operation="GetSavingsPlansPurchaseRecommendation",
        result_key="SavingsPlansPurchaseRecommendation",
        primary_keys=("recommendation_detail_id",),
        token_key="NextPageToken",
        granularity=None,
        page_size_key="PageSize",
        fan_out="recommendation_options",
    ),
    "purchase_recommendation_details": SavingsPlansEndpoint(
        operation="GetSavingsPlanPurchaseRecommendationDetails",
        result_key="RecommendationDetailData",
        primary_keys=("recommendation_detail_id",),
        token_key=None,
        granularity=None,
        fan_out="purchase_recommendations",
        parent_column="recommendation_detail_id",
    ),
}

# Cost Explorer only returns recommendations for one combination per request.
# The legacy *_UTILIZATION payment options apply to Reserved Instances, not Savings Plans.
# AWS sells Database Savings Plans only with a 1-year term and no upfront payment.
RECOMMENDATION_OPTIONS: tuple[dict[str, tuple[str, ...]], ...] = (
    {
        "SavingsPlansType": ("COMPUTE_SP", "EC2_INSTANCE_SP", "SAGEMAKER_SP"),
        "TermInYears": ("ONE_YEAR", "THREE_YEARS"),
        "PaymentOption": ("NO_UPFRONT", "PARTIAL_UPFRONT", "ALL_UPFRONT"),
        "LookbackPeriodInDays": ("SEVEN_DAYS", "THIRTY_DAYS", "SIXTY_DAYS"),
    },
    {
        "SavingsPlansType": ("DATABASE_SP",),
        "TermInYears": ("ONE_YEAR",),
        "PaymentOption": ("NO_UPFRONT",),
        "LookbackPeriodInDays": ("SEVEN_DAYS", "THIRTY_DAYS", "SIXTY_DAYS"),
    },
)

RECOMMENDATION_DECIMAL_FIELDS = (
    "upfront_cost",
    "estimated_roi",
    "estimated_sp_cost",
    "estimated_on_demand_cost",
    "estimated_on_demand_cost_with_current_commitment",
    "estimated_savings_amount",
    "estimated_savings_percentage",
    "hourly_commitment_to_purchase",
    "existing_hourly_commitment",
    "estimated_average_utilization",
    "estimated_monthly_savings_amount",
    "current_minimum_hourly_on_demand_spend",
    "current_maximum_hourly_on_demand_spend",
    "current_average_hourly_on_demand_spend",
    "current_average_coverage",
    "estimated_average_coverage",
)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [incremental_field("period_start")] for name, endpoint in ENDPOINTS.items() if endpoint.windowed
}

ENDPOINT_DESCRIPTIONS = {
    "savings_plans": "Savings Plans with their commitment, term, state, and payment details.",
    "utilization_daily": "Daily commitment use and savings across Savings Plans.",
    "utilization_details_daily": "Daily commitment use and savings for each Savings Plan.",
    "coverage_daily": "Daily spend covered by Savings Plans and remaining on-demand spend.",
    "savings_plan_offerings": "Savings Plans offerings with their plan type, term, payment option, and properties.",
    "savings_plan_rates": "Contracted rates of each Savings Plan by service, usage type, and operation.",
    "purchase_recommendations": "Recommended Savings Plans purchases with their expected cost and savings.",
    "purchase_recommendation_details": "Estimated cost, coverage, and utilization behind each purchase recommendation.",
}

ERROR_MESSAGES = {
    "AccessDenied": "AWS denied access. Grant the IAM read permission for the selected table.",
    "UnauthorizedException": "AWS denied access. Grant the IAM read permission for the selected table.",
    "UnrecognizedClientException": "AWS rejected the credentials. Check the access key ID and secret access key.",
    "InvalidClientTokenId": "AWS rejected the credentials. Check the access key ID and session token.",
    "InvalidSignatureException": "AWS rejected the signature. Check the secret access key and session token.",
    "SignatureDoesNotMatch": "AWS rejected the signature. Check the secret access key.",
    "ExpiredToken": "The AWS session token expired. Connect again with valid credentials.",
    "SubscriptionRequired": "Enable Cost Explorer in your AWS account, then try again.",
    "OptInRequired": "Enable Cost Explorer in your AWS account, then try again.",
    "DataUnavailableException": "AWS has no data for these dates. Enable Cost Explorer or select a later start date.",
    "BillExpirationException": "AWS no longer keeps data for these dates. Select a later start date.",
    "ValidationException": "AWS rejected the request. Check the source settings and try again.",
}
