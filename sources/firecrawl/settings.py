from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField

FIRECRAWL_BASE_URL = "https://api.firecrawl.dev"

PaginationMode = Literal["cursor", "offset", "none"]
PartitionFormat = Literal["month", "week", "day", "hour"]


@dataclass
class FirecrawlEndpointConfig:
    name: str
    path: str
    # Top-level key in the JSON body holding the row array (e.g. "data", "periods", "crawls").
    data_selector: str
    pagination: PaginationMode = "none"
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable datetime field to partition by. Only ever a creation-style column (never updated_at),
    # so partitions don't rewrite on every sync. None for endpoints without a stable timestamp.
    partition_key: Optional[str] = None
    partition_format: PartitionFormat = "week"
    should_sync_default: bool = True
    # monitor_checks fans out one offset-paginated request per monitor listed by /v2/monitor.
    # When True, `path` is a template with a `{monitor_id}` placeholder.
    fan_out_over_monitors: bool = False


# Firecrawl exposes account-level operational data alongside its scrape/crawl action endpoints.
# None of these list endpoints accept a server-side timestamp filter (verified against the public
# v2 API reference), so every table is full-refresh only - see firecrawl.py for the rationale.
FIRECRAWL_ENDPOINTS: dict[str, FirecrawlEndpointConfig] = {
    # Rolling 24h job log. Cursor-paginated. Retains only the last 24 hours, so frequent syncs are
    # needed to accumulate history and there is no way to backfill older activity.
    "team_activity": FirecrawlEndpointConfig(
        name="team_activity",
        path="/v2/team/activity",
        data_selector="data",
        pagination="cursor",
        primary_keys=["id"],
        partition_key="created_at",
    ),
    # Month-by-month credit usage. Small unpaginated list; the current period's total keeps growing,
    # so full refresh (replace) keeps it current.
    "credit_usage_historical": FirecrawlEndpointConfig(
        name="credit_usage_historical",
        path="/v2/team/credit-usage/historical",
        data_selector="periods",
        pagination="none",
        primary_keys=["startDate"],
    ),
    "token_usage_historical": FirecrawlEndpointConfig(
        name="token_usage_historical",
        path="/v2/team/token-usage/historical",
        data_selector="periods",
        pagination="none",
        primary_keys=["startDate"],
    ),
    # Point-in-time snapshot of in-flight crawls; rows vanish as crawls finish, so full refresh only.
    "active_crawls": FirecrawlEndpointConfig(
        name="active_crawls",
        path="/v2/crawl/active",
        data_selector="crawls",
        pagination="none",
        primary_keys=["id"],
    ),
    # Change-detection monitors. Offset-paginated.
    "monitors": FirecrawlEndpointConfig(
        name="monitors",
        path="/v2/monitor",
        data_selector="data",
        pagination="offset",
        primary_keys=["id"],
        partition_key="createdAt",
    ),
    # Per-monitor change-detection runs. Fans out one offset-paginated request per monitor, so it's
    # off by default to avoid the extra API cost on teams that don't need it.
    "monitor_checks": FirecrawlEndpointConfig(
        name="monitor_checks",
        path="/v2/monitor/{monitor_id}/checks",
        data_selector="data",
        pagination="offset",
        primary_keys=["id"],
        partition_key="createdAt",
        should_sync_default=False,
        fan_out_over_monitors=True,
    ),
}

ENDPOINTS = tuple(FIRECRAWL_ENDPOINTS.keys())

# Every endpoint is full-refresh: Firecrawl has no server-side timestamp filter on any of these list
# endpoints, so there is no genuine incremental cursor to advertise (a client-side "skip already-seen
# rows" pass would still page the whole endpoint, which is not incremental). Kept as an explicit empty
# mapping so `get_schemas` reads uniformly with the other sources.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
