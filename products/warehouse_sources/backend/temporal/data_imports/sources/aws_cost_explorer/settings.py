from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# Cost Explorer is a global service reached through us-east-1, so both the endpoint and the
# SigV4 signing region are fixed.
CE_ENDPOINT_URL = "https://ce.us-east-1.amazonaws.com/"
CE_SIGNING_REGION = "us-east-1"
CE_SIGNING_NAME = "ce"
CE_TARGET_PREFIX = "AWSInsightsIndexService"
CE_CONTENT_TYPE = "application/x-amz-json-1.1"

# Cost Explorer keeps 12 months of history for most operations, so a first sync with no
# explicit start date walks back a year.
DEFAULT_LOOKBACK_DAYS = 365

COST_METRICS = (
    "AmortizedCost",
    "BlendedCost",
    "NetAmortizedCost",
    "NetUnblendedCost",
    "UnblendedCost",
    "UsageQuantity",
)


@dataclass(frozen=True)
class CostExplorerEndpointConfig:
    name: str
    # Operation name, dispatched through the `X-Amz-Target` header.
    operation: str
    granularity: str
    # Response key holding the list of per-time-period results.
    result_key: str
    primary_key: list[str]
    # Pagination token key, identical in the request and the response. `None` for operations
    # that return everything in one shot (GetSavingsPlansUtilization).
    page_token_key: str | None = None
    metrics: tuple[str, ...] = ()
    group_by: tuple[str, ...] = ()
    # Days covered by a single request window. The API bills $0.01 per paginated request, so
    # windows are deliberately wide.
    window_days: int = 92
    # Cost Explorer restates recent periods (they come back flagged `Estimated`), so an
    # incremental run rewinds this far behind the stored watermark and re-merges.
    restatement_lookback_days: int = 7
    # Response sub-structures to flatten into the row, as (member name, column prefix) pairs.
    # An empty prefix keeps the sub-structure's own field names.
    nested_keys: tuple[tuple[str, str], ...] = field(default_factory=tuple)


AWS_COST_EXPLORER_ENDPOINTS: dict[str, CostExplorerEndpointConfig] = {
    "cost_and_usage_daily": CostExplorerEndpointConfig(
        name="cost_and_usage_daily",
        operation="GetCostAndUsage",
        granularity="DAILY",
        result_key="ResultsByTime",
        primary_key=["period_start", "service", "linked_account"],
        page_token_key="NextPageToken",
        metrics=COST_METRICS,
        group_by=("SERVICE", "LINKED_ACCOUNT"),
        window_days=92,
        restatement_lookback_days=7,
    ),
    "cost_and_usage_monthly": CostExplorerEndpointConfig(
        name="cost_and_usage_monthly",
        operation="GetCostAndUsage",
        granularity="MONTHLY",
        result_key="ResultsByTime",
        primary_key=["period_start", "service", "linked_account"],
        page_token_key="NextPageToken",
        metrics=COST_METRICS,
        group_by=("SERVICE", "LINKED_ACCOUNT"),
        window_days=366,
        restatement_lookback_days=45,
    ),
    "reservation_utilization_daily": CostExplorerEndpointConfig(
        name="reservation_utilization_daily",
        operation="GetReservationUtilization",
        granularity="DAILY",
        result_key="UtilizationsByTime",
        primary_key=["period_start"],
        page_token_key="NextPageToken",
        window_days=92,
        restatement_lookback_days=7,
        nested_keys=(("Total", ""),),
    ),
    "savings_plans_utilization_daily": CostExplorerEndpointConfig(
        name="savings_plans_utilization_daily",
        operation="GetSavingsPlansUtilization",
        granularity="DAILY",
        result_key="SavingsPlansUtilizationsByTime",
        primary_key=["period_start"],
        page_token_key=None,
        window_days=92,
        restatement_lookback_days=7,
        nested_keys=(
            ("Utilization", ""),
            ("Savings", "savings"),
            ("AmortizedCommitment", "amortized_commitment"),
        ),
    ),
}

ENDPOINTS = tuple(AWS_COST_EXPLORER_ENDPOINTS.keys())

# `period_start` is the window boundary the API itself filters on, so it is the only honest
# cursor: every operation takes a server-side `TimePeriod` and nothing else.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [
        {
            "label": "period_start",
            "type": IncrementalFieldType.DateTime,
            "field": "period_start",
            "field_type": IncrementalFieldType.DateTime,
        }
    ]
    for name in ENDPOINTS
}

ENDPOINT_DESCRIPTIONS: dict[str, str] = {
    "cost_and_usage_daily": "Daily cost and usage metrics grouped by AWS service and linked account.",
    "cost_and_usage_monthly": "Monthly cost and usage metrics grouped by AWS service and linked account.",
    "reservation_utilization_daily": "Daily Reserved Instance utilization and savings totals.",
    "savings_plans_utilization_daily": "Daily Savings Plans commitment utilization and net savings.",
}
