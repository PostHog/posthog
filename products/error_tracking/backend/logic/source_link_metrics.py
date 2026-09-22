"""Prometheus metrics for source link resolution. Label values are part of the dashboard contract."""

from prometheus_client import Counter, Histogram

SOURCE_LINK_REQUESTS = Counter(
    "error_tracking_source_link_requests_total",
    "Resolve requests by provider and outcome. 'linked' means at least one frame got a link.",
    labelnames=("provider", "outcome"),
)

SOURCE_LINK_FRAMES = Counter(
    "error_tracking_source_link_frames_total",
    "Frames that reached a provider, by whether they got a link.",
    labelnames=("provider", "outcome"),
)

SOURCE_LINK_RESOLVE_SECONDS = Histogram(
    "error_tracking_source_link_resolve_seconds",
    "Time to answer one resolve request, by provider.",
    labelnames=("provider",),
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60),
)

SOURCE_LINK_CACHE = Counter(
    "error_tracking_source_link_cache_total",
    "Cache lookups by cache and result.",
    labelnames=("cache", "result"),
)

SOURCE_LINK_TREE_LISTINGS = Counter(
    "error_tracking_source_link_tree_listings_total",
    "GitHub tree listings by result.",
    labelnames=("result",),
)

SOURCE_LINK_TREE_LISTING_REQUESTS = Histogram(
    "error_tracking_source_link_tree_listing_requests",
    "GitHub requests one tree listing made.",
    buckets=(1, 2, 3, 5, 10, 20, 50, 100),
)

SOURCE_LINK_SYMBOL_SET_READS = Counter(
    "error_tracking_source_link_symbol_set_reads_total",
    "Stored source map reads by result.",
    labelnames=("result",),
)

SOURCE_LINK_GITLAB_REQUESTS = Counter(
    "error_tracking_source_link_gitlab_requests_total",
    "GitLab search requests by response status.",
    labelnames=("status",),
)

SOURCE_LINK_PUBLIC_TOKEN = Counter(
    "error_tracking_source_link_public_token_total",
    "Shared GitHub token events.",
    labelnames=("event",),
)
