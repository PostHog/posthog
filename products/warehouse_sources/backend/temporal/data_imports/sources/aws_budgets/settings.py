from dataclasses import dataclass

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

# AWS Budgets is a global service: one endpoint for the whole partition, always signed against
# us-east-1 whatever region the customer works in.
BUDGETS_ENDPOINT_URL = "https://budgets.amazonaws.com/"
BUDGETS_SIGNING_REGION = "us-east-1"
BUDGETS_SIGNING_NAME = "budgets"
BUDGETS_TARGET_PREFIX = "AWSBudgetServiceGateway"
AWS_JSON_CONTENT_TYPE = "application/x-amz-json-1.1"

# Every Budgets operation requires the 12-digit account id, so it is derived once per sync from
# the credentials themselves instead of asking the customer to paste it. GetCallerIdentity needs
# no IAM permission, and STS is reached through its own global endpoint.
STS_ENDPOINT_URL = "https://sts.amazonaws.com/"
STS_SIGNING_REGION = "us-east-1"
STS_SIGNING_NAME = "sts"
STS_API_VERSION = "2011-06-15"

REQUEST_TIMEOUT_SECONDS = 60

# AWS keeps a limited window of budget history (60 days of DAILY periods, the current month plus
# 12 for MONTHLY, 4 quarters for QUARTERLY), so a year-wide first request covers every grain.
DEFAULT_HISTORY_LOOKBACK_DAYS = 365
# Actual spend for a period keeps moving until the bill finalizes, so an incremental run re-reads
# a trailing window rather than trusting the stored watermark.
HISTORY_RESTATEMENT_LOOKBACK_DAYS = 7

# DescribeBudgetPerformanceHistory covers DAILY, MONTHLY and QUARTERLY budgets only, so budgets on
# any other time unit are skipped instead of spending a request that cannot return history.
HISTORY_TIME_UNITS = frozenset({"DAILY", "MONTHLY", "QUARTERLY"})

# Members of the CostTypes structure. Emitted as columns on every row, present or not, so the
# table shape does not change with whichever budget happens to land in a batch.
COST_TYPE_MEMBERS = (
    "IncludeTax",
    "IncludeSubscription",
    "UseBlended",
    "IncludeRefund",
    "IncludeCredit",
    "IncludeUpfront",
    "IncludeRecurring",
    "IncludeOtherSubscription",
    "IncludeSupport",
    "IncludeDiscount",
    "UseAmortized",
)


@dataclass(frozen=True)
class AwsBudgetsEndpointConfig:
    name: str
    # Operation name, dispatched through the `X-Amz-Target` header.
    operation: str
    primary_key: list[str]
    # `MaxResults` per request. DescribeBudgets allows up to 1000, the per-budget operations 100.
    page_size: int
    # Per-budget operations are fanned out over the budgets DescribeBudgets returns.
    per_budget: bool = False
    # Only the history operation takes a server-side `TimePeriod`, which is what makes it the
    # single genuinely incremental table here.
    supports_time_period: bool = False
    partition_key: str | None = None


AWS_BUDGETS_ENDPOINTS: dict[str, AwsBudgetsEndpointConfig] = {
    "budgets": AwsBudgetsEndpointConfig(
        name="budgets",
        operation="DescribeBudgets",
        primary_key=["budget_name"],
        page_size=100,
    ),
    "budget_performance_history": AwsBudgetsEndpointConfig(
        name="budget_performance_history",
        operation="DescribeBudgetPerformanceHistory",
        primary_key=["budget_name", "period_start"],
        page_size=100,
        per_budget=True,
        supports_time_period=True,
        partition_key="period_start",
    ),
    "notifications": AwsBudgetsEndpointConfig(
        name="notifications",
        operation="DescribeNotificationsForBudget",
        # A notification carries no id of its own; a budget's notifications are distinguished by
        # the alert they describe.
        primary_key=["budget_name", "notification_type", "comparison_operator", "threshold", "threshold_type"],
        page_size=100,
        per_budget=True,
    ),
}

ENDPOINTS = tuple(AWS_BUDGETS_ENDPOINTS.keys())

# `budgets` and `notifications` have no server-side time filter at all, so they stay full refresh.
# `period_start` is the boundary the history operation itself filters on.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "budget_performance_history": [incremental_field("period_start")],
}

ENDPOINT_DESCRIPTIONS: dict[str, str] = {
    "budgets": "Budgets configured on the account, with their limit, actual spend, and forecasted spend.",
    "budget_performance_history": "Budgeted versus actual amounts for each period a budget has covered.",
    "notifications": "Alert thresholds attached to each budget, and whether they are currently in alarm.",
}
