from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_TRAFFIC_DOCS_URL = (
    "https://learn.microsoft.com/en-us/dotnet/api/microsoft.bing.webmaster.api.interfaces.iwebmasterapi.getquerystats"
)
_RANK_DOCS_URL = "https://learn.microsoft.com/en-us/dotnet/api/microsoft.bing.webmaster.api.interfaces.iwebmasterapi.getrankandtrafficstats"
_CRAWL_DOCS_URL = (
    "https://learn.microsoft.com/en-us/dotnet/api/microsoft.bing.webmaster.api.interfaces.iwebmasterapi.getcrawlstats"
)

_DATE_COLUMN = "The day the metrics were recorded, from Bing's `/Date(...)/` timestamp."

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "query_stats": {
        "description": "Daily search performance for the property's top queries.",
        "docs_url": _TRAFFIC_DOCS_URL,
        "columns": {
            "Query": "The search query the user typed.",
            "Date": _DATE_COLUMN,
            "Clicks": "Number of clicks the query drove to the property that day.",
            "Impressions": "Number of times the property appeared in results for the query that day.",
            "AvgClickPosition": "Average position of the property among results that were clicked.",
            "AvgImpressionPosition": "Average position of the property among results that were shown.",
        },
    },
    "page_stats": {
        "description": "Daily search performance for the property's top pages.",
        "docs_url": _TRAFFIC_DOCS_URL,
        "columns": {
            "Query": "The page URL. Bing returns page stats under the same `Query` field name as query stats.",
            "Date": _DATE_COLUMN,
            "Clicks": "Number of clicks the page received from search that day.",
            "Impressions": "Number of times the page appeared in search results that day.",
            "AvgClickPosition": "Average position of the page among results that were clicked.",
            "AvgImpressionPosition": "Average position of the page among results that were shown.",
        },
    },
    "rank_and_traffic_stats": {
        "description": "Daily clicks and impressions totals for the property across Bing search.",
        "docs_url": _RANK_DOCS_URL,
        "columns": {
            "Date": _DATE_COLUMN,
            "Clicks": "Total clicks to the property from search that day.",
            "Impressions": "Total times the property appeared in search results that day.",
        },
    },
    "crawl_stats": {
        "description": "Daily crawl statistics for the property, covering the last six months.",
        "docs_url": _CRAWL_DOCS_URL,
        "columns": {
            "Date": _DATE_COLUMN,
            "CrawledPages": "Pages Bing's crawler fetched that day.",
            "InIndex": "Pages of the property in the Bing index.",
            "InLinks": "Inbound links to the property Bing knows about.",
            "CrawlErrors": "Total crawl errors Bing encountered that day.",
            "Code2xx": "Pages that returned a 2xx (success) HTTP status.",
            "Code301": "Pages that returned a 301 (permanent redirect).",
            "Code302": "Pages that returned a 302 (temporary redirect).",
            "Code4xx": "Pages that returned a 4xx (client error) status.",
            "Code5xx": "Pages that returned a 5xx (server error) status.",
            "AllOtherCodes": "Pages that returned any other HTTP status.",
            "BlockedByRobotsTxt": "Pages Bing did not crawl because robots.txt blocked them.",
            "ContainsMalware": "Pages Bing flagged as containing malware.",
        },
    },
}
