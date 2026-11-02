from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# AskNicely caps (and defaults) the responses page size at 50,000 rows per request;
# stay well below that so a single page is cheap to parse and hold in memory.
RESPONSES_PAGE_SIZE = 5000

# The unsubscribed list defaults to 1,000 rows per page. Send it explicitly so page
# numbering stays stable even if the account default ever differs.
UNSUBSCRIBED_PAGE_SIZE = 1000

# AskNicely's warehousing-shaped GETs. The rest of the v1 API is either action-only
# (contact add/trigger, send survey) or a single-value rollup of `stats` (sentstats, getnps).
ENDPOINTS = ("responses", "stats", "contacts_unsubscribed")

PRIMARY_KEYS: dict[str, list[str]] = {
    "responses": ["response_id"],
    # `stats` labels each daily row with its date parts rather than carrying a date column.
    "stats": ["year", "month", "day"],
    "contacts_unsubscribed": ["id"],
}

# Only `responses` takes a server-side time cutoff (`since_time`). `stats` rows keep changing
# after their date — a survey sent on Monday and opened on Friday moves Monday's counts — and
# the unsubscribed list takes no time filter at all, so both sync as a full refresh.
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
