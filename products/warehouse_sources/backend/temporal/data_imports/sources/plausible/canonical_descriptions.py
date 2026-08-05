from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_DOCS_URL = "https://plausible.io/docs/stats-api"

# Metrics returned by the standard breakdown reports (everything except `goals`).
_STANDARD_METRIC_COLUMNS = {
    "date": "The day the metrics are aggregated over (YYYY-MM-DD), in the site's timezone.",
    "visitors": "Number of unique visitors.",
    "visits": "Number of visits/sessions.",
    "pageviews": "Number of pageview events.",
    "bounce_rate": "Percentage of visits with a single page interaction (0-100).",
    "visit_duration": "Average visit duration in seconds.",
    "events": "Number of events (pageviews plus custom events).",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "timeseries": {
        "description": "Site-wide traffic metrics aggregated per day.",
        "docs_url": _DOCS_URL,
        "columns": dict(_STANDARD_METRIC_COLUMNS),
    },
    "sources": {
        "description": "Daily traffic metrics broken down by acquisition source (channel).",
        "docs_url": _DOCS_URL,
        "columns": {**_STANDARD_METRIC_COLUMNS, "source": "The traffic source / channel a visit came from."},
    },
    "referrers": {
        "description": "Daily traffic metrics broken down by full referrer URL.",
        "docs_url": _DOCS_URL,
        "columns": {**_STANDARD_METRIC_COLUMNS, "referrer": "The full referrer URL a visit came from."},
    },
    "utm_sources": {
        "description": "Daily traffic metrics broken down by the utm_source query parameter.",
        "docs_url": _DOCS_URL,
        "columns": {**_STANDARD_METRIC_COLUMNS, "utm_source": "Value of the utm_source query parameter."},
    },
    "utm_mediums": {
        "description": "Daily traffic metrics broken down by the utm_medium query parameter.",
        "docs_url": _DOCS_URL,
        "columns": {**_STANDARD_METRIC_COLUMNS, "utm_medium": "Value of the utm_medium query parameter."},
    },
    "utm_campaigns": {
        "description": "Daily traffic metrics broken down by the utm_campaign query parameter.",
        "docs_url": _DOCS_URL,
        "columns": {**_STANDARD_METRIC_COLUMNS, "utm_campaign": "Value of the utm_campaign query parameter."},
    },
    "utm_terms": {
        "description": "Daily traffic metrics broken down by the utm_term query parameter.",
        "docs_url": _DOCS_URL,
        "columns": {**_STANDARD_METRIC_COLUMNS, "utm_term": "Value of the utm_term query parameter."},
    },
    "utm_contents": {
        "description": "Daily traffic metrics broken down by the utm_content query parameter.",
        "docs_url": _DOCS_URL,
        "columns": {**_STANDARD_METRIC_COLUMNS, "utm_content": "Value of the utm_content query parameter."},
    },
    "pages": {
        "description": "Daily traffic metrics broken down by page path.",
        "docs_url": _DOCS_URL,
        "columns": {**_STANDARD_METRIC_COLUMNS, "page": "The page path of the pageview."},
    },
    "entry_pages": {
        "description": "Daily traffic metrics broken down by the first page of each visit.",
        "docs_url": _DOCS_URL,
        "columns": {**_STANDARD_METRIC_COLUMNS, "entry_page": "The first page path visited in a session."},
    },
    "exit_pages": {
        "description": "Daily traffic metrics broken down by the last page of each visit.",
        "docs_url": _DOCS_URL,
        "columns": {**_STANDARD_METRIC_COLUMNS, "exit_page": "The last page path visited in a session."},
    },
    "countries": {
        "description": "Daily traffic metrics broken down by visitor country.",
        "docs_url": _DOCS_URL,
        "columns": {**_STANDARD_METRIC_COLUMNS, "country": "ISO 3166-1 alpha-2 country code of the visitor."},
    },
    "regions": {
        "description": "Daily traffic metrics broken down by visitor region.",
        "docs_url": _DOCS_URL,
        "columns": {**_STANDARD_METRIC_COLUMNS, "region": "ISO 3166-2 region code of the visitor."},
    },
    "cities": {
        "description": "Daily traffic metrics broken down by visitor city.",
        "docs_url": _DOCS_URL,
        "columns": {**_STANDARD_METRIC_COLUMNS, "city": "GeoNames ID of the visitor's city."},
    },
    "browsers": {
        "description": "Daily traffic metrics broken down by browser.",
        "docs_url": _DOCS_URL,
        "columns": {**_STANDARD_METRIC_COLUMNS, "browser": "The visitor's browser."},
    },
    "operating_systems": {
        "description": "Daily traffic metrics broken down by operating system.",
        "docs_url": _DOCS_URL,
        "columns": {**_STANDARD_METRIC_COLUMNS, "os": "The visitor's operating system."},
    },
    "devices": {
        "description": "Daily traffic metrics broken down by device type (screen size class).",
        "docs_url": _DOCS_URL,
        "columns": {**_STANDARD_METRIC_COLUMNS, "device": "Device type: Desktop, Mobile, Tablet, or Laptop."},
    },
    "goals": {
        "description": "Daily goal conversions broken down by goal.",
        "docs_url": _DOCS_URL,
        "columns": {
            "date": "The day the metrics are aggregated over (YYYY-MM-DD), in the site's timezone.",
            "goal": "The configured goal name (custom event or pageview goal).",
            "visitors": "Number of unique visitors who converted the goal.",
            "events": "Number of times the goal was converted.",
        },
    },
}
