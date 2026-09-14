from dataclasses import field
from typing import Any, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SortMode
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


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
    # Static query params sent with every request to this endpoint.
    params: dict[str, Any] = field(default_factory=dict)
    # The envelope key holding the rows of a paginated list response.
    items_selector: str = "Items"
    page_size_param: str = "perPage"
    # Set when the endpoint is reached once per row of a parent list endpoint, with the parent's
    # id formatted into `path`.
    parent: Optional[BunnyParentConfig] = None
    # Set for the statistics endpoints, whose body is a set of charts keyed by timestamp rather
    # than a list of objects. Maps each API chart property to the column its points land in.
    charts: Optional[dict[str, str]] = None
    # The column a chart's timestamp lands in. Doubles as the incremental cursor.
    timestamp_column: Optional[str] = None
    sort_mode: SortMode = "asc"


# The statistics endpoints all take the same server-side start filter.
DATE_FROM_PARAM = "dateFrom"

# bunny.net Core API list endpoints are full-refresh only: they expose no server-side
# `updated_after`-style filter, so there is no genuine incremental cursor to advance (a
# client-side scan of every page would cost the same as a full refresh — see the skill).
# The statistics endpoints do filter on `dateFrom`, so their tables sync incrementally on the
# chart timestamp — which is also how they keep history past the 30 days bunny.net returns by
# default.
BUNNY_ENDPOINTS: dict[str, BunnyEndpointConfig] = {
    "pull_zones": BunnyEndpointConfig(name="pull_zones", path="/pullzone"),
    "storage_zones": BunnyEndpointConfig(name="storage_zones", path="/storagezone"),
    "dns_zones": BunnyEndpointConfig(name="dns_zones", path="/dnszone", partition_key="DateCreated"),
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
