from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_ENGAGEMENT_DOCS = "https://developers.similarweb.com/reference/visits"

_SHARED_COLUMNS = {
    "domain": "Domain the metric was requested for, as configured on the source.",
    "country": "Country filter the metric was requested with; `world` for worldwide data.",
    "granularity": "Length of the period each row covers: daily, weekly or monthly.",
    "date": "Start of the period the row measures, as a timestamp.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "visits": {
        "description": "Estimated total visits to the domain from desktop and mobile web, per period.",
        "docs_url": _ENGAGEMENT_DOCS,
        "columns": {
            **_SHARED_COLUMNS,
            "visits": "Estimated number of visits in the period, desktop and mobile web combined.",
        },
    },
    "page_views": {
        "description": "Estimated total page views for the domain from desktop and mobile web, per period.",
        "docs_url": "https://developers.similarweb.com/reference/page-views",
        "columns": {
            **_SHARED_COLUMNS,
            "pages_views": "Estimated number of page views in the period. Similarweb returns this field as `pages_views`.",
        },
    },
    "pages_per_visit": {
        "description": "Average number of pages viewed during a visit to the domain, per period.",
        "docs_url": "https://developers.similarweb.com/reference/pages-per-visit",
        "columns": {
            **_SHARED_COLUMNS,
            "pages_per_visit": "Average pages viewed per visit in the period.",
        },
    },
    "average_visit_duration": {
        "description": "Average length of a visit to the domain, in seconds, per period.",
        "docs_url": "https://developers.similarweb.com/reference/average-visit-duration-all-traffic",
        "columns": {
            **_SHARED_COLUMNS,
            "average_visit_duration": "Average visit duration in seconds for the period.",
        },
    },
    "bounce_rate": {
        "description": "Share of visits to the domain that ended without further interaction, per period.",
        "docs_url": "https://developers.similarweb.com/reference/bounce-rate",
        "columns": {
            **_SHARED_COLUMNS,
            "bounce_rate": "Bounce rate for the period as a fraction between 0 and 1.",
        },
    },
    "global_rank": {
        "description": "Similarweb's worldwide traffic rank for the domain, by month. "
        "The endpoint is worldwide and monthly only, so it takes no country or granularity filter.",
        "docs_url": "https://developers.similarweb.com/reference/global-rank",
        "columns": {
            "domain": "Domain the rank was requested for, as configured on the source.",
            "date": "First day of the month the rank applies to, as a timestamp.",
            "global_rank": "Worldwide rank of the domain that month, where 1 is the most visited site.",
        },
    },
    "traffic_sources": {
        "description": "Visits to the domain split by marketing channel and by organic versus paid, per period.",
        "docs_url": "https://developers.similarweb.com/reference/traffic-sources-overview",
        "columns": {
            **_SHARED_COLUMNS,
            "source_type": "Marketing channel the visits came from: Search, Social, Mail, Display Ads, Direct or Referrals.",
            "organic": "Estimated unpaid visits from the channel in the period.",
            "paid": "Estimated paid visits from the channel in the period.",
        },
    },
    "traffic_by_country": {
        "description": "Traffic share and engagement for the domain broken down by visitor country, "
        "aggregated over the whole synced window rather than per period.",
        "docs_url": "https://developers.similarweb.com/reference/geography-total",
        "columns": {
            "domain": "Domain the breakdown was requested for, as configured on the source.",
            "country": "ISO 3166-1 numeric code of the visitors' country.",
            "country_name": "Name of the visitors' country.",
            "share": "Share of the domain's total visits that came from the country, between 0 and 1.",
            "visits": "Estimated visits from the country over the requested window.",
            "pages_per_visit": "Average pages viewed per visit by visitors from the country.",
            "average_time": "Average visit duration in seconds for visitors from the country.",
            "bounce_rate": "Bounce rate for visitors from the country, as a fraction between 0 and 1.",
            "rank": "Rank of the domain within that country's websites.",
        },
    },
}
