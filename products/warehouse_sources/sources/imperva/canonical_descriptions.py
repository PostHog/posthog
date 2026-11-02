from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.imperva.settings import (
    SITES_DOCS_URL,
    STATS_DOCS_URL,
)

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "sites": {
        "description": "Websites associated with the selected Imperva account.",
        "docs_url": SITES_DOCS_URL,
        "columns": {
            "id": "Unique site identifier.",
            "accountId": "Identifier of the account that owns the site.",
            "name": "Website name.",
            "siteStatus": "Site configuration status.",
        },
    },
    "visits_timeseries": {
        "description": "Daily account visit counts, split by human and bot traffic.",
        "docs_url": STATS_DOCS_URL,
        "columns": {
            "account_id": "Account requested for this statistic.",
            "id": "Identifier of the statistic series.",
            "name": "Name of the statistic series.",
            "timestamp": "Start of the daily interval in milliseconds since the Unix epoch.",
            "value": "Number of visits in the interval.",
        },
    },
    "hits_timeseries": {
        "description": "Daily account hit statistics for human, bot, and blocked traffic, including rates per second.",
        "docs_url": STATS_DOCS_URL,
        "columns": {
            "account_id": "Account requested for this statistic.",
            "id": "Identifier of the statistic series.",
            "name": "Name of the statistic series.",
            "timestamp": "Start of the daily interval in milliseconds since the Unix epoch.",
            "value": "Hit count or rate per second, as identified by the series.",
        },
    },
    "bandwidth_timeseries": {
        "description": "Daily account bandwidth and throughput between clients and Imperva proxy servers.",
        "docs_url": STATS_DOCS_URL,
        "columns": {
            "account_id": "Account requested for this statistic.",
            "id": "Identifier of the statistic series.",
            "name": "Name of the statistic series.",
            "timestamp": "Start of the daily interval in milliseconds since the Unix epoch.",
            "value": "Transferred bytes or throughput in bits per second, as identified by the series.",
        },
    },
}
