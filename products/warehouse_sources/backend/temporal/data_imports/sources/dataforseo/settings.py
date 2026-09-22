import dataclasses
from typing import Any, Literal

from posthog.dataclasses import frozen

# DataForSEO serves every dataset as a POST "live" endpoint under https://api.dataforseo.com/v3.
# The request body is an array with one task object ({"target": ..., "location_name": ...}) and
# the response nests data as tasks[].result[] (with result[].items[] for most Labs endpoints).
# Every request is billed by DataForSEO, so the transport caps targets and pages per target.
#
# No endpoint exposes a server-side updated-since filter, so every table is full refresh only.
# The `kind` tells the transport how to turn tasks[].result[] into flat rows.
ParseKind = Literal["items", "ranked_keywords", "monthly_items", "result_rows", "lookup_rows"]


@frozen
class DataForSEOEndpointConfig:
    name: str
    # Path under the API base (https://api.dataforseo.com/v3).
    path: str
    kind: ParseKind
    # Unique across the whole table. Every endpoint fans out over the user's configured targets,
    # so the injected `target` is always part of the key.
    primary_keys: list[str]
    # The Labs reference tables are free GET lookups; every other endpoint is a billed POST task.
    method: Literal["GET", "POST"] = "POST"
    # Whether the endpoint is scoped to a target domain. Untargeted endpoints are global lookup
    # tables: no fan-out, no injected `target`, no pagination.
    targeted: bool = True
    # Whether the endpoint accepts `limit`/`offset` pagination (Labs list endpoints).
    paginated: bool = False
    # Whether the request payload carries location_name/language_name (Labs endpoints do; the
    # Backlinks API has no location concept).
    localized: bool = True
    # Static extra payload fields sent on every request for this endpoint.
    extra_payload: dict[str, Any] = dataclasses.field(default_factory=dict)
    # A stable date column used for datetime partitioning. Only set where rows carry a
    # never-changing date (historical months); snapshot tables hold few rows per target.
    partition_key: str | None = None
    description: str | None = None
    should_sync_default: bool = True


DATAFORSEO_ENDPOINTS: dict[str, DataForSEOEndpointConfig] = {
    "domain_rank_overview": DataForSEOEndpointConfig(
        name="domain_rank_overview",
        path="/dataforseo_labs/google/domain_rank_overview/live",
        kind="items",
        primary_keys=["target"],
        description="Current organic and paid ranking distribution, estimated traffic value, and keyword counts per target domain (one row per target). Full refresh.",
    ),
    "historical_rank_overview": DataForSEOEndpointConfig(
        name="historical_rank_overview",
        path="/dataforseo_labs/google/historical_rank_overview/live",
        kind="monthly_items",
        primary_keys=["target", "year", "month"],
        # DataForSEO's documented minimum for date_from; without it the API returns only the
        # trailing 6 months, which is too little history for a warehouse.
        extra_payload={"date_from": "2020-10-01"},
        partition_key="date",
        description="Monthly history of organic and paid ranking metrics per target domain since October 2020 (one row per target per month). Full refresh.",
    ),
    "ranked_keywords": DataForSEOEndpointConfig(
        name="ranked_keywords",
        path="/dataforseo_labs/google/ranked_keywords/live",
        kind="ranked_keywords",
        primary_keys=["target", "keyword", "item_type", "rank_absolute"],
        paginated=True,
        description="Keywords each target domain ranks for in Google, with the ranked SERP element and keyword metrics like search volume and CPC. Full refresh.",
    ),
    "competitors_domain": DataForSEOEndpointConfig(
        name="competitors_domain",
        path="/dataforseo_labs/google/competitors_domain/live",
        kind="items",
        primary_keys=["target", "domain"],
        paginated=True,
        description="Competitor domains ranking for the same keywords as each target domain, with intersection counts and ranking metrics. Full refresh.",
    ),
    "backlinks_summary": DataForSEOEndpointConfig(
        name="backlinks_summary",
        path="/backlinks/summary/live",
        kind="result_rows",
        primary_keys=["target"],
        localized=False,
        extra_payload={"include_subdomains": True},
        description="Backlink profile summary per target domain: rank, total backlinks, referring domains, IPs, and link attributes (one row per target). Requires an active DataForSEO Backlinks API subscription. Full refresh.",
        should_sync_default=False,
    ),
    "relevant_pages": DataForSEOEndpointConfig(
        name="relevant_pages",
        path="/dataforseo_labs/google/relevant_pages/live",
        kind="items",
        primary_keys=["target", "page_address"],
        paginated=True,
        description="Landing pages of each target domain that rank in Google, with per-page estimated traffic, keyword counts, and position distribution. Full refresh.",
    ),
    "backlinks_referring_domains": DataForSEOEndpointConfig(
        name="backlinks_referring_domains",
        path="/backlinks/referring_domains/live",
        kind="items",
        primary_keys=["target", "domain"],
        paginated=True,
        localized=False,
        extra_payload={"include_subdomains": True},
        description="Domains linking to each target domain, with domain rank, backlink and referring counts, spam score, and first-seen and lost dates (one row per referring domain). Requires an active DataForSEO Backlinks API subscription. Full refresh.",
        should_sync_default=False,
    ),
    "backlinks_history": DataForSEOEndpointConfig(
        name="backlinks_history",
        path="/backlinks/history/live",
        kind="items",
        primary_keys=["target", "date"],
        localized=False,
        partition_key="date",
        description="Month-by-month history of each target domain's backlink profile since January 2019: rank, backlinks, referring domains, and crawl statistics. Requires an active DataForSEO Backlinks API subscription. Full refresh.",
        should_sync_default=False,
    ),
    "backlinks_timeseries_summary": DataForSEOEndpointConfig(
        name="backlinks_timeseries_summary",
        path="/backlinks/timeseries_summary/live",
        kind="items",
        primary_keys=["target", "date"],
        localized=False,
        # Unlike /backlinks/history/live, this endpoint does not default date_from to its documented
        # minimum, so ask for the full range explicitly.
        extra_payload={"date_from": "2019-01-30", "group_range": "month", "include_subdomains": True},
        partition_key="date",
        description="Monthly trend of each target domain's link profile since January 2019: backlinks, referring domains, pages, IPs, and subnets, with nofollow splits. Requires an active DataForSEO Backlinks API subscription. Full refresh.",
        should_sync_default=False,
    ),
    "locations_and_languages": DataForSEOEndpointConfig(
        name="locations_and_languages",
        path="/dataforseo_labs/locations_and_languages",
        kind="lookup_rows",
        primary_keys=["location_code"],
        method="GET",
        targeted=False,
        localized=False,
        description="Reference table of every location DataForSEO Labs supports, with the languages available for each. Resolves the location_code and language_code carried on the other Labs tables. Full refresh.",
    ),
    "categories": DataForSEOEndpointConfig(
        name="categories",
        path="/dataforseo_labs/categories",
        kind="lookup_rows",
        primary_keys=["category_code"],
        method="GET",
        targeted=False,
        localized=False,
        description="Reference table of the DataForSEO Labs category taxonomy, with each category's parent code. Resolves the category codes carried on the other Labs tables. Full refresh.",
    ),
}

ENDPOINTS = tuple(DATAFORSEO_ENDPOINTS.keys())
