from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

ENDPOINTS = (
    "Costs",
    "Dimensions",
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

# Partition key per endpoint (stable business dates only — never a `_at`/`lastSeen`-style field).
PARTITION_KEYS: dict[str, str | None] = {
    "Costs": "usage_date",
    "Dimensions": None,
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
