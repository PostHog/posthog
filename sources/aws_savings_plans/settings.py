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


ENDPOINTS: dict[str, SavingsPlansEndpoint] = {
    "savings_plans": SavingsPlansEndpoint(
        operation="DescribeSavingsPlans",
        result_key="savingsPlans",
        primary_keys=("savings_plan_arn",),
        service="savingsplans",
        token_key="nextToken",
        granularity=None,
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
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [incremental_field("period_start")] for name, endpoint in ENDPOINTS.items() if endpoint.service == "ce"
}

ENDPOINT_DESCRIPTIONS = {
    "savings_plans": "Savings Plans with their commitment, term, state, and payment details.",
    "utilization_daily": "Daily commitment use and savings across Savings Plans.",
    "utilization_details_daily": "Daily commitment use and savings for each Savings Plan.",
    "coverage_daily": "Daily spend covered by Savings Plans and remaining on-demand spend.",
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
