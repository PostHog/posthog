from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
    CanonicalEndpoint,
)

_SEARCH_ANALYTICS_DOCS_URL = "https://developers.google.com/webmaster-tools/v1/searchanalytics/query"
_SITES_DOCS_URL = "https://developers.google.com/webmaster-tools/v1/sites/list"
_SITEMAPS_DOCS_URL = "https://developers.google.com/webmaster-tools/v1/sitemaps/list"

# Every search analytics table carries the same four metrics, plus the dimensions it groups by.
_METRIC_COLUMNS = {
    "clicks": "Number of clicks on a result that led to the property.",
    "impressions": "Number of times a link to the property appeared in search results for the user.",
    "ctr": "Click-through rate, as a fraction between 0 and 1 (clicks divided by impressions).",
    "position": "Average position of the property's topmost result, where 1 is the top result.",
}

_DATE_COLUMN = {
    "date": "The day the metrics were recorded, in Pacific time (UTC-7:00/8:00).",
}

_SEARCH_TYPE_COLUMN = {
    "search_type": "The Google Search tab the metrics come from: web, image, video, or news.",
}


def _web_search_analytics(description: str, **dimensions: str) -> CanonicalEndpoint:
    """A table on Search Analytics' default `type`, which is web results only."""
    return {
        "description": f"{description} Covers web search only.",
        "docs_url": _SEARCH_ANALYTICS_DOCS_URL,
        "columns": {**_DATE_COLUMN, **dimensions, **_METRIC_COLUMNS},
    }


def _search_analytics_by_type(description: str, **dimensions: str) -> CanonicalEndpoint:
    """A table that queries every search type and keeps the type as a column."""
    return {
        "description": description,
        "docs_url": _SEARCH_ANALYTICS_DOCS_URL,
        "columns": {**_DATE_COLUMN, **_SEARCH_TYPE_COLUMN, **dimensions, **_METRIC_COLUMNS},
    }


_QUERY_COLUMN = "The search query the user typed. Queries made by very few users are withheld by Google."
_PAGE_COLUMN = "The canonical URL of the result page the user saw."
_COUNTRY_COLUMN = "Country the search was made from, as a three-letter ISO 3166-1 alpha-3 code."
_DEVICE_COLUMN = "Device the search was made on: DESKTOP, MOBILE, or TABLET."

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "search_analytics_by_date": _web_search_analytics("Daily search performance totals for the property."),
    "search_analytics_by_query": _web_search_analytics(
        "Daily search performance for the property, grouped by search query.",
        query=_QUERY_COLUMN,
    ),
    "search_analytics_by_page": _web_search_analytics(
        "Daily search performance for the property, grouped by landing page.",
        page=_PAGE_COLUMN,
    ),
    "search_analytics_by_country": _web_search_analytics(
        "Daily search performance for the property, grouped by the searcher's country.",
        country=_COUNTRY_COLUMN,
    ),
    "search_analytics_by_device": _web_search_analytics(
        "Daily search performance for the property, grouped by device type.",
        device=_DEVICE_COLUMN,
    ),
    "search_analytics_by_country_device": _web_search_analytics(
        "Daily search performance for the property, grouped by country and device together.",
        country=_COUNTRY_COLUMN,
        device=_DEVICE_COLUMN,
    ),
    "search_analytics_by_query_country": _web_search_analytics(
        "Daily search performance for the property, grouped by search query and the searcher's country.",
        query=_QUERY_COLUMN,
        country=_COUNTRY_COLUMN,
    ),
    "search_analytics_by_query_device": _web_search_analytics(
        "Daily search performance for the property, grouped by search query and device type.",
        query=_QUERY_COLUMN,
        device=_DEVICE_COLUMN,
    ),
    "search_analytics_by_page_country": _web_search_analytics(
        "Daily search performance for the property, grouped by landing page and the searcher's country.",
        page=_PAGE_COLUMN,
        country=_COUNTRY_COLUMN,
    ),
    "search_analytics_by_page_device": _web_search_analytics(
        "Daily search performance for the property, grouped by landing page and device type.",
        page=_PAGE_COLUMN,
        device=_DEVICE_COLUMN,
    ),
    "search_analytics_by_page_country_device": _web_search_analytics(
        "Daily search performance for the property, grouped by landing page, country, and device together.",
        page=_PAGE_COLUMN,
        country=_COUNTRY_COLUMN,
        device=_DEVICE_COLUMN,
    ),
    "search_analytics_by_query_page": _web_search_analytics(
        "Daily search performance for the property, grouped by search query and landing page.",
        query=_QUERY_COLUMN,
        page=_PAGE_COLUMN,
    ),
    "search_analytics_by_search_appearance": _web_search_analytics(
        "Daily search performance for the property, grouped by how the result was presented in search.",
        searchAppearance="The search result feature the result appeared as, for example RICH_RESULT or VIDEO.",
    ),
    "search_analytics_by_hour": _web_search_analytics(
        "Hourly search performance totals for the property, covering the last 10 days.",
        hour="Start of the hour the metrics were recorded, in Pacific time (UTC-7:00/8:00).",
    ),
    "search_analytics_by_search_type": _search_analytics_by_type(
        "Daily search performance totals for the property, split by search type."
    ),
    "search_analytics_by_query_search_type": _search_analytics_by_type(
        "Daily search performance for the property, grouped by search query and split by search type.",
        query=_QUERY_COLUMN,
    ),
    "search_analytics_by_page_search_type": _search_analytics_by_type(
        "Daily search performance for the property, grouped by landing page and split by search type.",
        page=_PAGE_COLUMN,
    ),
    "sites": {
        "description": "Search Console properties the connected Google account has access to.",
        "docs_url": _SITES_DOCS_URL,
        "columns": {
            "siteUrl": "The property, either a URL prefix such as https://example.com/ or a domain property such as sc-domain:example.com.",
            "permissionLevel": "The account's permission level on the property: SITE_OWNER, SITE_FULL_USER, SITE_RESTRICTED_USER, or SITE_UNVERIFIED_USER.",
        },
    },
    "sitemaps": {
        "description": "Sitemaps submitted for the property, with Google's processing status for each.",
        "docs_url": _SITEMAPS_DOCS_URL,
        "columns": {
            "path": "The URL of the sitemap.",
            "type": "The type of sitemap, for example SITEMAP, RSS_FEED, ATOM_FEED, or URL_LIST.",
            "lastSubmitted": "When the sitemap was submitted to Google.",
            "lastDownloaded": "When Google last downloaded the sitemap.",
            "errors": "Number of errors in the sitemap itself, which stop it being processed correctly.",
            "warnings": "Number of warnings for URLs in the sitemap. Generally non-critical.",
            "isPending": "True while Google has not yet processed the sitemap.",
            "isSitemapsIndex": "True when the sitemap is an index that points at other sitemaps.",
        },
    },
    "sitemap_contents": {
        "description": "URL counts per content type for each submitted sitemap, one row per sitemap and content type.",
        "docs_url": _SITEMAPS_DOCS_URL,
        "columns": {
            "path": "The URL of the sitemap this content type belongs to.",
            "type": "The content type, for example WEB, IMAGE, VIDEO, or NEWS.",
            "submitted": "Number of URLs of this content type in the sitemap.",
        },
    },
}
