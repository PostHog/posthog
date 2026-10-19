from dataclasses import field
from typing import Any, Literal

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField

ANALYTICS_BASE_URL = "https://api-admin.adapty.io"
SERVER_BASE_URL = "https://api.adapty.io"
CHART_IDS = (
    "revenue",
    "mrr",
    "arr",
    "arppu",
    "subscriptions_active",
    "subscriptions_new",
    "subscriptions_renewal_cancelled",
    "subscriptions_expired",
    "trials_active",
    "trials_new",
    "trials_renewal_cancelled",
    "trials_expired",
    "grace_period",
    "billing_issue",
    "refund_events",
    "refund_money",
    "non_subscriptions",
    "arpu",
    "installs",
)


@frozen
class AdaptyEndpoint:
    path: str
    primary_keys: tuple[str, ...]
    partition_key: str = "date"
    shape: Literal["metrics", "report", "paywalls"] = "report"
    body: dict[str, Any] = field(default_factory=dict)


ENDPOINTS: dict[str, AdaptyEndpoint] = {
    "Analytics": AdaptyEndpoint(
        path="/api/v1/client-api/metrics/analytics/",
        primary_keys=("date", "chart_id", "metric"),
        shape="metrics",
        body={"period_unit": "day", "date_type": "purchase_date"},
    ),
    "Cohorts": AdaptyEndpoint(
        path="/api/v1/client-api/metrics/cohort/",
        primary_keys=("date",),
        body={"period_unit": "day", "period_type": "renewals", "value_field": "revenue", "value_type": "absolute"},
    ),
    "Conversions": AdaptyEndpoint(
        path="/api/v1/client-api/metrics/conversion/",
        primary_keys=("date",),
        body={"period_unit": "day", "date_type": "purchase_date", "from_period": "1", "to_period": "6+"},
    ),
    "Funnels": AdaptyEndpoint(
        path="/api/v1/client-api/metrics/funnel/", primary_keys=("date",), body={"show_value_as": "both"}
    ),
    "LTV": AdaptyEndpoint(
        path="/api/v1/client-api/metrics/ltv/",
        primary_keys=("date", "metric"),
        shape="metrics",
        body={"period_unit": "day", "period_type": "renewals"},
    ),
    "Retention": AdaptyEndpoint(
        path="/api/v1/client-api/metrics/retention/", primary_keys=("date",), body={"use_trial": False}
    ),
    "Paywalls": AdaptyEndpoint(
        path="/api/v2/server-side-api/paywalls/",
        primary_keys=("paywall_id",),
        partition_key="created_at",
        shape="paywalls",
    ),
}

# Historical aggregates can change after renewals and refunds. The date filter also needs account verification.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in ENDPOINTS}
