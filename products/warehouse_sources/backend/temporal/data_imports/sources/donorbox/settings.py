from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

API_VERSION = "v1"
API_BASE_URL = "https://donorbox.org/api/"
API_DOCS_URL = "https://github.com/donorbox/donorbox-api/blob/master/README.md"
PAGE_SIZE = 100
PRIMARY_KEYS = ["id"]
PARTITION_SIZE = 100_000

ENDPOINTS = {
    "campaigns": "campaigns",
    "donations": "donations",
    "plans": "plans",
    "donors": "donors",
    "events": "events",
    "tickets": "tickets",
    "purchases": "purchases",
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "donations": [
        {
            "label": "Donation date",
            "field": "donation_date",
            "type": IncrementalFieldType.DateTime,
            "field_type": IncrementalFieldType.DateTime,
        }
    ],
    "plans": [
        {
            "label": "Start date",
            "field": "started_at",
            "type": IncrementalFieldType.Date,
            "field_type": IncrementalFieldType.Date,
        }
    ],
}

AUTH_ERROR = "Donorbox authentication failed. Check your organization login email and API key."
ACCESS_ERROR = "Donorbox denied API access. Enable API & Zapier Integration in your Donorbox account."
NON_RETRYABLE_ERRORS = {
    "401 Client Error": AUTH_ERROR,
    "403 Client Error": ACCESS_ERROR,
    "Authentication failed": AUTH_ERROR,
}
