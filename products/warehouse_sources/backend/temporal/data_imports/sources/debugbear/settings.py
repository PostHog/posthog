from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

ENDPOINTS = (
    "Projects",
    "PageMetrics",
)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "PageMetrics": [
        {
            "label": "analysis_date",
            "type": IncrementalFieldType.DateTime,
            "field": "analysis_date",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
}

# DebugBear's `pageMetrics` endpoint only exposes a `before` cutoff (walk backward through
# history); there is no forward `since`/`after` filter, so incremental syncs simply stop
# paginating once a whole page's results are no newer than the watermark instead of asking
# the API to filter server-side.
BEFORE_PARAM = "before"
