from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# AskNicely caps (and defaults) the responses page size at 50,000 rows per request;
# stay well below that so a single page is cheap to parse and hold in memory.
RESPONSES_PAGE_SIZE = 5000

# The responses history is AskNicely's one warehousing-shaped stream. The other API
# endpoints (contact add/trigger, send survey) are action-only and return no history.
ENDPOINTS = ("responses",)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "responses": [
        {
            "label": "responded",
            "type": IncrementalFieldType.DateTime,
            "field": "responded",
            "field_type": IncrementalFieldType.Integer,
        },
    ],
}
