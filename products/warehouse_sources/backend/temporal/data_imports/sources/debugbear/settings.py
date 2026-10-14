from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

ENDPOINTS = (
    "Projects",
    "Pages",
    "PageMetrics",
    "RumMetrics",
    "RumPageViews",
    "Annotations",
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
    "RumMetrics": [
        {
            "label": "date",
            "type": IncrementalFieldType.DateTime,
            "field": "date",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
    "RumPageViews": [
        {
            "label": "date",
            "type": IncrementalFieldType.DateTime,
            "field": "date",
            "field_type": IncrementalFieldType.DateTime,
        },
    ],
}

# DebugBear's `pageMetrics` endpoint only exposes a `before` cutoff (walk backward through
# history); there is no forward `since`/`after` filter, so incremental syncs simply stop
# paginating once a whole page's results are no newer than the watermark instead of asking
# the API to filter server-side.
BEFORE_PARAM = "before"

# `rumMetrics` aggregates the whole range into one value per metric unless `groupByTime`
# splits it into buckets. Daily buckets give a row grain that merges cleanly and lets the
# watermark advance.
RUM_GROUP_BY_TIME = "day"

# Neither RUM endpoint reports how far back a project's data goes, so a first sync asks for
# a year and the API returns whatever falls inside the account's retention.
RUM_BACKFILL_DAYS = 365

# `rumPageViews` returns at most 5000 rows per request (the documented maximum for `count`).
RUM_PAGE_VIEWS_PAGE_SIZE = 5000
