from typing import Any, TypedDict

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

ENDPOINTS = (
    "Budgets",
    "Costs",
    "Dimensions",
    "Insights",
    "RecommendationTypes",
    "Recommendations",
)

INCREMENTAL_ENDPOINTS = ("Costs",)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "Costs": [
        {
            "label": "usage_date",
            "type": IncrementalFieldType.DateTime,
            "field": "usage_date",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
}


class ListEndpointSettings(TypedDict):
    path: str
    table_name: str
    # jsonpath to the row array in the response envelope, or None when the body is a bare array.
    data_selector: str | None
    # True for the v2 list envelope, which carries the next page under `pagination.cursor`.
    # False for endpoints that answer in a single page.
    paginated: bool
    params: dict[str, Any]


# Read-only list endpoints. `Costs` is not here: it takes user-chosen query options and is the
# only endpoint with a server-side time filter, so it is built separately in `cloudzero.py`.
LIST_ENDPOINTS: dict[str, ListEndpointSettings] = {
    "Budgets": {
        "path": "/v2/budgets",
        "table_name": "budgets",
        "data_selector": "budgets",
        "paginated": True,
        # `current` adds the period's actual and planned spend to each budget, which is what
        # makes a budget-versus-actual comparison against the Costs table possible.
        "params": {"expand": ["current"]},
    },
    "Dimensions": {
        "path": "/v2/billing/dimensions",
        "table_name": "dimensions",
        "data_selector": "dimensions",
        "paginated": False,
        "params": {"include_hidden": "true"},
    },
    "Insights": {
        "path": "/v2/insights",
        "table_name": "insights",
        "data_selector": "insights",
        "paginated": True,
        "params": {},
    },
    "RecommendationTypes": {
        "path": "/v2/optimize/recommendation_types",
        "table_name": "recommendation_types",
        # This endpoint answers with a bare JSON array rather than the v2 list envelope.
        "data_selector": None,
        "paginated": False,
        "params": {},
    },
    "Recommendations": {
        "path": "/v2/optimize/recommendations",
        "table_name": "recommendations",
        "data_selector": "recommendations",
        "paginated": True,
        # CloudZero defaults this endpoint to 60,000 rows per page. A smaller page keeps the
        # in-memory page bounded and gives the resumable cursor a checkpoint per page.
        "params": {"limit": 1000},
    },
}

# Primary key per endpoint. `Costs` is absent because its key depends on the dimensions the user
# groups by, so `source_for_pipeline` assembles it.
PRIMARY_KEYS: dict[str, list[str]] = {
    "Budgets": ["id"],
    "Dimensions": ["id"],
    "Insights": ["id"],
    "RecommendationTypes": ["id"],
    "Recommendations": ["recommendation_id"],
}

# Partition key per endpoint (stable business dates only — never a `_at`/`lastSeen`-style field).
PARTITION_KEYS: dict[str, str | None] = {
    "Budgets": None,
    "Costs": "usage_date",
    "Dimensions": None,
    "Insights": None,
    "RecommendationTypes": None,
    "Recommendations": None,
}

# CloudZero's earliest documented cost data; used as the start_date floor for a full (non-incremental) sync.
DEFAULT_START_DATE = "2025-01-01T00:00:00+00:00"

# CloudZero can restate historical costs after the fact, so incremental syncs roll the start_date
# back by this many days to recapture any values that changed since the last sync.
RESTATEMENT_WINDOW_DAYS = 7

GRANULARITY_OPTIONS = ("hourly", "daily", "weekly", "monthly", "yearly")

COST_TYPE_OPTIONS = (
    "billed_cost",
    "discounted_cost",
    "amortized_cost",
    "discounted_amortized_cost",
    "real_cost",
    "on_demand_cost",
    "invoiced_amortized_cost",
    "usage_amount",
)
