from dataclasses import field
from datetime import timedelta
from typing import Any, Optional

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType, SortMode, frozen


@frozen
class BunnyParentConfig:
    """A list endpoint whose rows a child endpoint is reached once per."""

    endpoint: str
    id_field: str
    id_column: str


@frozen
class BunnyEndpointConfig:
    name: str
    path: str
    # bunny.net object IDs are globally unique within an account, so `Id` is a safe primary key.
    primary_keys: list[str] = field(default_factory=lambda: ["Id"])
    # A stable (never-rewritten) datetime field to partition by. Only set where the object
    # actually exposes a creation timestamp — never `DateModified`, which changes on every edit.
    partition_key: Optional[str] = None
    # Stream endpoints answer on a different host and authenticate with the per-library key
    # `/videolibrary` carries, not the account API key.
    stream_api: bool = False
    # The CDN Logging API answers on its own host, but still takes the account API key.
    logging_api: bool = False
    # Static query params sent with every request to this endpoint.
    params: dict[str, Any] = field(default_factory=dict)
    # The envelope key holding the rows of a paginated list response. None when the body itself
    # is the row list.
    items_selector: Optional[str] = "Items"
    page_size_param: str = "perPage"
    # False for an endpoint that answers with every row in one unpaginated body.
    paginated: bool = True
    # Set when the endpoint is reached once per row of a parent list endpoint, with the parent's
    # id formatted into `path`.
    parent: Optional[BunnyParentConfig] = None
    # Set for the statistics endpoints, whose body is a set of charts keyed by timestamp rather
    # than a list of objects. Maps each API chart property to the column its points land in.
    charts: Optional[dict[str, str]] = None
    # The column holding the instant a row covers. Doubles as the incremental cursor, so it is
    # only set where the endpoint filters server-side on it.
    timestamp_column: Optional[str] = None
    sort_mode: SortMode = "asc"
    # Set when the parent is itself a fan-out child (`videos`), so `path` takes the library id as
    # `id` and the video guid as `video`. The body is one map from segment index to intensity.
    per_video: bool = False


# The statistics endpoints all take the same server-side start filter.
DATE_FROM_PARAM = "dateFrom"

# The Logging API names its own window start differently, and serves entries from a rolling
# retention window only. It rejects a query that starts before that window, so a run asks from
# the later of the watermark and the oldest instant still retained.
LOG_DATE_FROM_PARAM = "from"
# `to` defaults to the moment the API handles each request, so a run that fixes it once and
# reuses it for every page and pull zone queries a stable window instead of one that keeps
# growing as new entries land during the walk. Without this a busy zone's `hasMore` could stay
# true indefinitely.
LOG_DATE_TO_PARAM = "to"
LOG_RETENTION = timedelta(days=3)
# The window end defaults to the moment the API handles the request, so the start is held just
# inside the retention edge to leave room for that and for request latency.
LOG_WINDOW_MARGIN = timedelta(minutes=5)
# A log row carries the request's decrypted `Authorization` header when the zone has extended
# logging on. That is a live end-user credential no analysis needs, so it never reaches a table.
LOG_EXCLUDED_FIELDS = frozenset({"authorizationHeader"})

# bunny.net Core API list endpoints are full-refresh only: they expose no server-side
# `updated_after`-style filter, so there is no genuine incremental cursor to advance (a
# client-side scan of every page would cost the same as a full refresh — see the skill).
# The statistics endpoints do filter on `dateFrom`, so their tables sync incrementally on the
# chart timestamp — which is also how they keep history past the 30 days bunny.net returns by
# default. The Logging API filters the same way, on its own window start.
BUNNY_ENDPOINTS: dict[str, BunnyEndpointConfig] = {
    "pull_zones": BunnyEndpointConfig(name="pull_zones", path="/pullzone"),
    "storage_zones": BunnyEndpointConfig(name="storage_zones", path="/storagezone"),
    "dns_zones": BunnyEndpointConfig(name="dns_zones", path="/dnszone", partition_key="DateCreated"),
    "dns_records": BunnyEndpointConfig(
        name="dns_records",
        path="/dnszone/{id}/records",
        # A record id is only documented as unique inside its zone, so the zone id is part of
        # the key.
        primary_keys=["DnsZoneId", "Id"],
        parent=BunnyParentConfig(endpoint="dns_zones", id_field="Id", id_column="DnsZoneId"),
    ),
    "video_libraries": BunnyEndpointConfig(name="video_libraries", path="/videolibrary", partition_key="DateCreated"),
    "statistics": BunnyEndpointConfig(
        name="statistics",
        path="/statistics",
        primary_keys=["Timestamp"],
        partition_key="Timestamp",
        timestamp_column="Timestamp",
        # Every chart defaults to off, so each one this table has a column for is asked for by
        # name. Geographic distribution and user balance history are left out: they are keyed by
        # country and by account event, not by the timestamp this table is grained on.
        params={
            "loadBandwidthUsed": "true",
            "loadRequestsServed": "true",
            "loadOriginTraffic": "true",
            "loadOriginResponseTimes": "true",
            "loadOriginShieldBandwidth": "true",
            "loadErrors": "true",
        },
        charts={
            "BandwidthUsedChart": "BandwidthUsed",
            "BandwidthCachedChart": "BandwidthCached",
            "CacheHitRateChart": "CacheHitRate",
            "RequestsServedChart": "RequestsServed",
            "PullRequestsPulledChart": "PullRequestsPulled",
            "OriginTrafficChart": "OriginTraffic",
            "OriginResponseTimeChart": "OriginResponseTime",
            "OriginShieldBandwidthUsedChart": "OriginShieldBandwidthUsed",
            "OriginShieldInternalBandwidthUsedChart": "OriginShieldInternalBandwidthUsed",
            "Error3xxChart": "Error3xx",
            "Error4xxChart": "Error4xx",
            "Error5xxChart": "Error5xx",
        },
    ),
    "storage_zone_statistics": BunnyEndpointConfig(
        name="storage_zone_statistics",
        path="/storagezone/{id}/statistics",
        primary_keys=["StorageZoneId", "Timestamp"],
        partition_key="Timestamp",
        timestamp_column="Timestamp",
        parent=BunnyParentConfig(endpoint="storage_zones", id_field="Id", id_column="StorageZoneId"),
        charts={"StorageUsedChart": "StorageUsed", "FileCountChart": "FileCount"},
        # Rows arrive grouped by storage zone, so the table as a whole is not in timestamp order.
        # "desc" holds the watermark until the run finishes, otherwise a run cut short mid-walk
        # would advance it past zones it never reached.
        sort_mode="desc",
    ),
    "storage_zone_egress": BunnyEndpointConfig(
        name="storage_zone_egress",
        path="/storagezone/{id}/statistics/egress",
        primary_keys=["StorageZoneId", "Timestamp"],
        partition_key="Timestamp",
        timestamp_column="Timestamp",
        parent=BunnyParentConfig(endpoint="storage_zones", id_field="Id", id_column="StorageZoneId"),
        charts={
            "HttpEgressChart": "HttpEgress",
            "S3EgressChart": "S3Egress",
            "S3PresignedEgressChart": "S3PresignedEgress",
            "FtpEgressChart": "FtpEgress",
            "SftpEgressChart": "SftpEgress",
            "TotalEgressChart": "TotalEgress",
        },
        sort_mode="desc",
    ),
    "dns_zone_statistics": BunnyEndpointConfig(
        name="dns_zone_statistics",
        path="/dnszone/{id}/statistics",
        primary_keys=["DnsZoneId", "Timestamp"],
        partition_key="Timestamp",
        timestamp_column="Timestamp",
        parent=BunnyParentConfig(endpoint="dns_zones", id_field="Id", id_column="DnsZoneId"),
        # The query-type breakdown the same body carries is keyed by record type rather than by
        # time, so it belongs to a different grain and is left out of this table.
        charts={
            "QueriesServedChart": "QueriesServed",
            "NormalQueriesServedChart": "NormalQueriesServed",
            "SmartQueriesServedChart": "SmartQueriesServed",
        },
        sort_mode="desc",
    ),
    "pull_zone_logs": BunnyEndpointConfig(
        name="pull_zone_logs",
        path="/v2/pullzones/{id}/logs",
        primary_keys=["pullZoneId", "requestId"],
        partition_key="timestamp",
        logging_api=True,
        timestamp_column="timestamp",
        # Offset pagination is only stable while already-read rows keep their offset, so entries
        # are read oldest first and newly arrived ones land past the pages already walked.
        params={"order": "asc"},
        items_selector="data",
        parent=BunnyParentConfig(endpoint="pull_zones", id_field="Id", id_column="pullZoneId"),
        # Rows arrive grouped by pull zone, so the table as a whole is not in timestamp order.
        sort_mode="desc",
    ),
    "billing_summary": BunnyEndpointConfig(
        name="billing_summary",
        path="/billing/summary",
        # One row per pull zone with its usage so far in the current month.
        primary_keys=["PullZoneId"],
        items_selector=None,
        paginated=False,
    ),
    "pull_zone_optimizer_statistics": BunnyEndpointConfig(
        name="pull_zone_optimizer_statistics",
        path="/pullzone/{id}/optimizer/statistics",
        primary_keys=["PullZoneId", "Timestamp"],
        partition_key="Timestamp",
        timestamp_column="Timestamp",
        parent=BunnyParentConfig(endpoint="pull_zones", id_field="Id", id_column="PullZoneId"),
        charts={
            "RequestsOptimizedChart": "RequestsOptimized",
            "AverageCompressionChart": "AverageCompression",
            "TrafficSavedChart": "TrafficSaved",
            "AverageProcessingTimeChart": "AverageProcessingTime",
        },
        sort_mode="desc",
    ),
    "pull_zone_safehop_statistics": BunnyEndpointConfig(
        name="pull_zone_safehop_statistics",
        path="/pullzone/{id}/safehop/statistics",
        primary_keys=["PullZoneId", "Timestamp"],
        partition_key="Timestamp",
        timestamp_column="Timestamp",
        parent=BunnyParentConfig(endpoint="pull_zones", id_field="Id", id_column="PullZoneId"),
        charts={"RequestsRetriedChart": "RequestsRetried", "RequestsSavedChart": "RequestsSaved"},
        sort_mode="desc",
    ),
    "pull_zone_origin_shield_queue_statistics": BunnyEndpointConfig(
        name="pull_zone_origin_shield_queue_statistics",
        path="/pullzone/{id}/originshield/queuestatistics",
        primary_keys=["PullZoneId", "Timestamp"],
        partition_key="Timestamp",
        timestamp_column="Timestamp",
        parent=BunnyParentConfig(endpoint="pull_zones", id_field="Id", id_column="PullZoneId"),
        charts={"ConcurrentRequestsChart": "ConcurrentRequests", "QueuedRequestsChart": "QueuedRequests"},
        sort_mode="desc",
    ),
    "videos": BunnyEndpointConfig(
        name="videos",
        path="/library/{id}/videos",
        # `guid` is only documented as unique inside its library, so the library id is part of
        # the key — a fan-out child aggregates rows from every parent into one table.
        primary_keys=["videoLibraryId", "guid"],
        partition_key="dateUploaded",
        stream_api=True,
        params={"orderBy": "date"},
        items_selector="items",
        page_size_param="itemsPerPage",
        parent=BunnyParentConfig(endpoint="video_libraries", id_field="Id", id_column="videoLibraryId"),
    ),
    "video_collections": BunnyEndpointConfig(
        name="video_collections",
        path="/library/{id}/collections",
        primary_keys=["videoLibraryId", "guid"],
        stream_api=True,
        params={"orderBy": "date"},
        items_selector="items",
        page_size_param="itemsPerPage",
        parent=BunnyParentConfig(endpoint="video_libraries", id_field="Id", id_column="videoLibraryId"),
    ),
    "video_heatmaps": BunnyEndpointConfig(
        name="video_heatmaps",
        path="/library/{id}/videos/{video}/heatmap",
        # A segment index is only meaningful inside its video, and a guid inside its library.
        primary_keys=["videoLibraryId", "videoGuid", "segment"],
        stream_api=True,
        parent=BunnyParentConfig(endpoint="videos", id_field="guid", id_column="videoGuid"),
        per_video=True,
    ),
    "video_library_statistics": BunnyEndpointConfig(
        name="video_library_statistics",
        path="/library/{id}/statistics",
        primary_keys=["videoLibraryId", "timestamp"],
        partition_key="timestamp",
        stream_api=True,
        timestamp_column="timestamp",
        parent=BunnyParentConfig(endpoint="video_libraries", id_field="Id", id_column="videoLibraryId"),
        # The country breakdowns the same body carries are keyed by country rather than by time,
        # so they belong to a different grain and are left out of this table.
        charts={"viewsChart": "views", "watchTimeChart": "watchTime"},
        sort_mode="desc",
    ),
}

ENDPOINTS = tuple(BUNNY_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [
        {
            "label": config.timestamp_column,
            "type": IncrementalFieldType.DateTime,
            "field": config.timestamp_column,
            "field_type": IncrementalFieldType.DateTime,
        }
    ]
    for name, config in BUNNY_ENDPOINTS.items()
    if config.timestamp_column is not None
}
