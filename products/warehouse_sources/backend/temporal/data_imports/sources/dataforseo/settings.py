import dataclasses
from typing import Any, Literal

# DataForSEO serves every dataset as a POST "live" endpoint under https://api.dataforseo.com/v3.
# The request body is an array with one task object ({"target": ..., "location_name": ...}) and
# the response nests data as tasks[].result[] (with result[].items[] for most Labs endpoints).
# Every request is billed by DataForSEO, so the transport caps targets and pages per target.
#
# No endpoint exposes a server-side updated-since filter, so every table is full refresh only.
# The `kind` tells the transport how to turn tasks[].result[] into flat rows.
ParseKind = Literal["items", "ranked_keywords", "monthly_items", "result_rows"]


@dataclasses.dataclass
class DataForSEOEndpointConfig:
    name: str
    # Path under the API base (https://api.dataforseo.com/v3).
    path: str
    kind: ParseKind
    # Unique across the whole table. Every endpoint fans out over the user's configured targets,
    # so the injected `target` is always part of the key.
    primary_keys: list[str]
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
}

ENDPOINTS = tuple(DATAFORSEO_ENDPOINTS.keys())
