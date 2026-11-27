from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Literal

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType

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
    # `None` for GetDimensionValues, which has no granularity member.
    granularity: str | None
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
    # Only cost-and-usage operations return a flagged-`Estimated` figure for the current,
    # still-in-progress day. The utilization operations have no such concept and reject a
    # request whose window includes today with DataUnavailableException.
    includes_current_day: bool = False
    # GetDimensionValues: one request series per dimension, each row keyed by dimension + value.
    dimensions: tuple[str, ...] = ()
    # One request series per service, filtered on SERVICE and tagged with a `service` column.
    # GetReservationCoverage reports only EC2 when the request has no SERVICE filter.
    services: tuple[str, ...] = ()
    # Days before today the operation serves at all. GetCostAndUsageWithResources rejects a
    # start date more than 14 days back.
    max_lookback_days: int | None = None
    # GetCostAndUsageWithResources requires a filter, so each window is filtered to the services
    # GetDimensionValues reports for it, which keeps every service in scope.
    filter_by_window_services: bool = False
    # AWS reports reservation coverage in normalized usage units only for services with
    # instance-size-flexible reservations; asking for "Unit" against any other service in
    # `services` raises a ValidationException. Empty means no service needs filtering out.
    unit_metric_services: tuple[str, ...] = ()
    # "history" walks back over past windows. "forecast" asks for one window that starts today and
    # runs `forecast_days` forward. "snapshot" sends no TimePeriod, because the recommendation
    # operations report the current state.
    time_scope: Literal["history", "forecast", "snapshot"] = "history"
    forecast_days: int = 0
    # One request series per value, sent as this request member and tagged as a snake_case column.
    slice_member: str | None = None
    slice_values: tuple[str, ...] = ()
    # Request members sent unchanged on every call.
    static_payload: Mapping[str, Any] = field(default_factory=dict)
    # "periods": one result per time period. "items": one row per item of `result_key`, with the
    # period from the item or, failing that, from the response. "records": one row per item of
    # `result_key` (or per item of its `detail_member` list), with every string kept as AWS sent
    # it, because these records mix account IDs such as `012345678901` with amounts.
    row_shape: Literal["periods", "items", "records"] = "periods"
    # "items" only: string maps kept uncoerced and flattened under a prefix, as (member, prefix).
    label_members: tuple[tuple[str, str], ...] = ()
    detail_member: str | None = None
    # Records with no ID of their own get a `recommendation_key` hashed from their identifying fields.
    synthetic_key: bool = False


# Services that support reservations and accept the AWS service name as a SERVICE value.
RESERVATION_SERVICES = (
    "Amazon Elastic Compute Cloud - Compute",
    "Amazon Relational Database Service",
    "Amazon ElastiCache",
    "Amazon Redshift",
)

FORECAST_METRICS = (
    "AMORTIZED_COST",
    "BLENDED_COST",
    "NET_AMORTIZED_COST",
    "NET_UNBLENDED_COST",
    "UNBLENDED_COST",
)


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
        includes_current_day=True,
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
        includes_current_day=True,
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
    "dimension_values": CostExplorerEndpointConfig(
        name="dimension_values",
        operation="GetDimensionValues",
        granularity=None,
        result_key="DimensionValues",
        primary_key=["dimension", "value"],
        page_token_key="NextPageToken",
        dimensions=("LINKED_ACCOUNT", "SERVICE", "REGION"),
        # One window over the whole range, so a value active in several windows is listed once.
        window_days=100 * 366,
        includes_current_day=True,
    ),
    "cost_and_usage_with_resources_daily": CostExplorerEndpointConfig(
        name="cost_and_usage_with_resources_daily",
        operation="GetCostAndUsageWithResources",
        granularity="DAILY",
        result_key="ResultsByTime",
        primary_key=["period_start", "service", "resource_id"],
        page_token_key="NextPageToken",
        metrics=COST_METRICS,
        group_by=("SERVICE", "RESOURCE_ID"),
        window_days=14,
        restatement_lookback_days=7,
        includes_current_day=True,
        max_lookback_days=14,
        filter_by_window_services=True,
    ),
    "reservation_coverage_daily": CostExplorerEndpointConfig(
        name="reservation_coverage_daily",
        operation="GetReservationCoverage",
        granularity="DAILY",
        result_key="CoveragesByTime",
        primary_key=["period_start", "service"],
        page_token_key="NextPageToken",
        metrics=("Hour", "Unit", "Cost"),
        services=RESERVATION_SERVICES,
        window_days=92,
        restatement_lookback_days=7,
        nested_keys=(("Total", ""),),
        unit_metric_services=("Amazon Elastic Compute Cloud - Compute",),
    ),
    "savings_plans_coverage_daily": CostExplorerEndpointConfig(
        name="savings_plans_coverage_daily",
        operation="GetSavingsPlansCoverage",
        granularity="DAILY",
        result_key="SavingsPlansCoverages",
        primary_key=["period_start"],
        page_token_key="NextToken",
        metrics=("SpendCoveredBySavingsPlans",),
        window_days=92,
        restatement_lookback_days=7,
        nested_keys=(("Coverage", ""),),
    ),
    "savings_plans_utilization_details_daily": CostExplorerEndpointConfig(
        name="savings_plans_utilization_details_daily",
        operation="GetSavingsPlansUtilizationDetails",
        # The operation has no granularity member and aggregates over the whole TimePeriod, so a
        # one-day window is the only way to get a daily row per Savings Plan.
        granularity=None,
        result_key="SavingsPlansUtilizationDetails",
        primary_key=["period_start", "savings_plan_arn"],
        page_token_key="NextToken",
        window_days=1,
        restatement_lookback_days=7,
        row_shape="items",
        nested_keys=(
            ("Utilization", ""),
            ("Savings", "savings"),
            ("AmortizedCommitment", "amortized_commitment"),
        ),
        label_members=(("Attributes", "attribute"),),
    ),
    "cost_forecast_daily": CostExplorerEndpointConfig(
        name="cost_forecast_daily",
        operation="GetCostForecast",
        granularity="DAILY",
        result_key="ForecastResultsByTime",
        primary_key=["period_start", "metric"],
        time_scope="forecast",
        # AWS serves 3 months of DAILY forecasts. 89 days fits every 3-month span.
        forecast_days=89,
        slice_member="Metric",
        slice_values=FORECAST_METRICS,
        static_payload={"PredictionIntervalLevel": 80},
        row_shape="items",
    ),
    "rightsizing_recommendations": CostExplorerEndpointConfig(
        name="rightsizing_recommendations",
        operation="GetRightsizingRecommendation",
        granularity=None,
        result_key="RightsizingRecommendations",
        primary_key=["account_id", "current_instance_resource_id"],
        page_token_key="NextPageToken",
        time_scope="snapshot",
        static_payload={"Service": "AmazonEC2", "PageSize": 1000},
        row_shape="records",
    ),
    "reservation_purchase_recommendations": CostExplorerEndpointConfig(
        name="reservation_purchase_recommendations",
        operation="GetReservationPurchaseRecommendation",
        granularity=None,
        result_key="Recommendations",
        primary_key=["recommendation_key"],
        page_token_key="NextPageToken",
        time_scope="snapshot",
        slice_member="Service",
        slice_values=RESERVATION_SERVICES,
        static_payload={
            "TermInYears": "ONE_YEAR",
            "PaymentOption": "NO_UPFRONT",
            "LookbackPeriodInDays": "THIRTY_DAYS",
            "PageSize": 1000,
        },
        row_shape="records",
        detail_member="RecommendationDetails",
        synthetic_key=True,
    ),
}

ENDPOINTS = tuple(AWS_COST_EXPLORER_ENDPOINTS.keys())

# `period_start` is the window boundary the API itself filters on, so it is the only honest
# cursor: every operation takes a server-side `TimePeriod` and nothing else. Dimension values,
# forecasts and recommendations are a current view rather than a history, so those tables are
# full refresh only.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [
        {
            "label": "period_start",
            "type": IncrementalFieldType.DateTime,
            "field": "period_start",
            "field_type": IncrementalFieldType.DateTime,
        }
    ]
    for name, endpoint_config in AWS_COST_EXPLORER_ENDPOINTS.items()
    if not endpoint_config.dimensions and endpoint_config.time_scope == "history"
}

ENDPOINT_DESCRIPTIONS: dict[str, str] = {
    "cost_and_usage_daily": "Daily cost and usage metrics grouped by AWS service and linked account.",
    "cost_and_usage_monthly": "Monthly cost and usage metrics grouped by AWS service and linked account.",
    "reservation_utilization_daily": "Daily Reserved Instance utilization and savings totals.",
    "savings_plans_utilization_daily": "Daily Savings Plans commitment utilization and net savings.",
    "dimension_values": "Linked accounts, services and regions seen in the synced range, with linked account names.",
    "cost_and_usage_with_resources_daily": "Daily cost and usage per resource for the last 14 days. Requires resource-level data to be enabled in Cost Explorer settings.",
    "reservation_coverage_daily": "Daily share of eligible EC2, RDS, ElastiCache and Redshift usage covered by reservations.",
    "savings_plans_coverage_daily": "Daily share of eligible spend covered by Savings Plans, and the remaining On-Demand cost.",
    "savings_plans_utilization_details_daily": "Daily utilization, savings and amortized commitment for each Savings Plan. Uses one billed request per day.",
    "cost_forecast_daily": "Forecast spend for each of the next 89 days, per cost metric, with an 80% prediction interval.",
    "rightsizing_recommendations": "Current recommendations to downsize or terminate idle and underused EC2 instances. Requires rightsizing recommendations to be turned on in Cost Explorer preferences.",
    "reservation_purchase_recommendations": "Current Reserved Instance purchase recommendations for EC2, RDS, ElastiCache and Redshift, for a 1-year No Upfront term based on the last 30 days of usage.",
}
