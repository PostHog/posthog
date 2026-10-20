from products.warehouse_sources.backend.temporal.data_imports.sources.common.canonical_descriptions import (
    CanonicalDescriptions,
)

_API_DOCS_BASE = "https://learn.microsoft.com/en-us/dotnet/api/microsoft.bing.webmaster.api.interfaces.iwebmasterapi"

_SITE_URL_COLUMN = {
    "site_url": "The verified site these statistics belong to, as listed in Bing Webmaster Tools.",
}

_DATE_COLUMN = {
    "date": "The day the data point was recorded.",
}

# GetQueryStats and GetPageStats return the same QueryStats shape; for page stats the `query`
# field carries the page URL instead of a search query.
_QUERY_STATS_METRIC_COLUMNS = {
    "impressions": "Number of times the site appeared in Bing search results.",
    "clicks": "Number of clicks on the site's results.",
    "avg_click_position": "Average position of the site's result among impressions that were clicked.",
    "avg_impression_position": "Average position at which the site appeared in search results.",
}

CANONICAL_DESCRIPTIONS: CanonicalDescriptions = {
    "sites": {
        "description": "Sites registered on the connected Bing Webmaster Tools account and whether each one is verified.",
        "docs_url": f"{_API_DOCS_BASE}.getusersites",
        "columns": {
            "url": "The site URL as registered in Bing Webmaster Tools.",
            "is_verified": "Whether ownership of the site has been verified.",
        },
    },
    "query_stats": {
        "description": (
            "Traffic statistics for the site's top search queries on Bing. Bing updates this data "
            "weekly and retains about six months."
        ),
        "docs_url": f"{_API_DOCS_BASE}.getquerystats",
        "columns": {
            **_DATE_COLUMN,
            "query": "The search query users typed.",
            **_QUERY_STATS_METRIC_COLUMNS,
            **_SITE_URL_COLUMN,
        },
    },
    "page_stats": {
        "description": (
            "Traffic statistics for the site's top pages on Bing. Bing updates this data weekly "
            "and retains about six months."
        ),
        "docs_url": f"{_API_DOCS_BASE}.getpagestats",
        "columns": {
            **_DATE_COLUMN,
            "query": "The page URL (the API returns pages in its query field).",
            **_QUERY_STATS_METRIC_COLUMNS,
            **_SITE_URL_COLUMN,
        },
    },
    "rank_and_traffic_stats": {
        "description": (
            "Daily impressions and clicks for the site in Bing search. Since March 24, 2023 the "
            "counts cover all Bing verticals: web, chat, news, images, videos, and knowledge panel."
        ),
        "docs_url": f"{_API_DOCS_BASE}.getrankandtrafficstats",
        "columns": {
            **_DATE_COLUMN,
            "impressions": "Number of times the site appeared in Bing search results on this day.",
            "clicks": "Number of clicks on the site's results on this day.",
            **_SITE_URL_COLUMN,
        },
    },
    "crawl_stats": {
        "description": "Daily Bingbot crawl activity for the site over the last six months.",
        "docs_url": f"{_API_DOCS_BASE}.getcrawlstats",
        "columns": {
            **_DATE_COLUMN,
            "crawled_pages": "Number of pages Bingbot crawled.",
            "in_index": "Number of the site's pages in the Bing index.",
            "in_links": "Number of inbound links Bing has discovered to the site.",
            "crawl_errors": "Number of pages that returned a crawl error.",
            "blocked_by_robots_txt": "Number of pages blocked from crawling by robots.txt.",
            "code2xx": "Number of crawled pages that returned an HTTP 2xx status.",
            "code301": "Number of crawled pages that returned an HTTP 301 redirect.",
            "code302": "Number of crawled pages that returned an HTTP 302 redirect.",
            "code4xx": "Number of crawled pages that returned an HTTP 4xx error.",
            "code5xx": "Number of crawled pages that returned an HTTP 5xx error.",
            "all_other_codes": "Number of crawled pages that returned any other HTTP status.",
            "connection_timeout": "Number of crawl attempts that timed out connecting.",
            "dns_failures": "Number of crawl attempts that failed DNS resolution.",
            **_SITE_URL_COLUMN,
        },
    },
    "page_query_stats": {
        "description": (
            "Traffic statistics for each search query that led to each of the site's top pages on Bing. "
            "Bing updates this data weekly and retains about six months."
        ),
        "docs_url": f"{_API_DOCS_BASE}.getpagequerystats",
        "columns": {
            "page": "The page URL the statistics are for, taken from the site's top pages.",
            **_DATE_COLUMN,
            "query": "The search query users typed before they saw or clicked the page.",
            **_QUERY_STATS_METRIC_COLUMNS,
            **_SITE_URL_COLUMN,
        },
    },
    "crawl_issues": {
        "description": "The site's URLs that currently have crawl issues in Bing.",
        "docs_url": f"{_API_DOCS_BASE}.getcrawlissues",
        "columns": {
            "url": "The URL that has crawl issues.",
            "http_code": "The HTTP status code Bingbot received for the URL.",
            "issues": (
                "Bit flags for the issue types found: 1 = HTTP 301, 2 = HTTP 302, 4 = HTTP 4xx, "
                "8 = HTTP 5xx, 16 = blocked by robots.txt, 32 = contains malware, 64 = important URL "
                "blocked by robots.txt, 128 = DNS errors, 256 = timeout errors."
            ),
            "in_links": "Number of inbound links Bing found to the URL.",
            **_SITE_URL_COLUMN,
        },
    },
    "link_counts": {
        "description": "The site's pages that have inbound links, with the number of inbound links for each.",
        "docs_url": f"{_API_DOCS_BASE}.getlinkcounts",
        "columns": {
            "url": "The page URL on the site.",
            "count": "Number of inbound links Bing found to the page.",
            **_SITE_URL_COLUMN,
        },
    },
}
