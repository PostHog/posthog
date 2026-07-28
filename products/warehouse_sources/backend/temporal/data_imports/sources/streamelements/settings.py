from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

STREAMELEMENTS_BASE_URL = "https://api.streamelements.com/kappa/v2"

# Documented cap for tips/activities list endpoints (limit must be 1-100).
DEFAULT_PAGE_SIZE = 100
# Points leaderboards accept bigger pages: verified live that limit=1000 returns rows while
# larger values silently return an empty list.
LEADERBOARD_PAGE_SIZE = 1000

# The activity feed only returns events whose type is listed, so ask for every documented type.
ACTIVITY_TYPES = [
    "follow",
    "tip",
    "host",
    "cheer",
    "raid",
    "subscriber",
    "sponsor",
    "superchat",
    "redemption",
    "merch",
]

# How an endpoint is fetched. Routed on in `streamelements.py:streamelements_source`.
#   "offset"     -> limit/offset pagination, optionally unwrapping a body key via data_selector
#   "activities" -> GET /activities/{channel}, paged by walking the `before` datetime bound down
#   "single"     -> whole result in one un-paginated response
EndpointKind = Literal["offset", "activities", "single"]


@dataclass
class StreamElementsEndpointConfig:
    name: str
    # "{channel}" is replaced with the channel id resolved from GET /channels/me.
    path: str
    kind: EndpointKind
    primary_keys: list[str] = field(default_factory=lambda: ["_id"])
    # Body key the row list is wrapped under (e.g. {"docs": [...]}); None for bare-array bodies.
    data_selector: Optional[str] = None
    # jsonpath of the grand-total count in wrapped responses, used to stop offset pagination.
    total_path: Optional[str] = None
    # False only for endpoints returning a single object rather than a list of rows.
    returns_list: bool = True
    # Stable (never-changing) datetime field used for datetime partitioning.
    partition_key: Optional[str] = None
    page_size: int = DEFAULT_PAGE_SIZE
    # Static query params sent on every request.
    params: dict[str, Any] = field(default_factory=dict)
    incremental_fields: list[IncrementalField] = field(default_factory=list)

    @property
    def supports_incremental(self) -> bool:
        return len(self.incremental_fields) > 0


STREAMELEMENTS_ENDPOINTS: dict[str, StreamElementsEndpointConfig] = {
    "tips": StreamElementsEndpointConfig(
        name="tips",
        path="/tips/{channel}",
        kind="offset",
        data_selector="docs",
        total_path="total",
        partition_key="createdAt",
        # createdAt ascending is a documented sort value, keeping offset pages stable while
        # new tips arrive mid-sync and letting the incremental watermark advance per batch.
        params={"sort": "createdAt"},
        incremental_fields=[incremental_field("createdAt")],
    ),
    "activities": StreamElementsEndpointConfig(
        name="activities",
        path="/activities/{channel}",
        kind="activities",
        partition_key="createdAt",
        # The bounds and origin are required even when defaults would do; origin is any
        # caller-chosen identifier.
        params={
            "types": ACTIVITY_TYPES,
            "mincheer": 0,
            "minhost": 0,
            "minsub": 0,
            "mintip": 0,
            "origin": "posthog",
        },
        incremental_fields=[incremental_field("createdAt")],
    ),
    "store_redemptions": StreamElementsEndpointConfig(
        name="store_redemptions",
        path="/store/{channel}/redemptions",
        kind="offset",
        data_selector="docs",
        total_path="total",
        partition_key="createdAt",
    ),
    "store_items": StreamElementsEndpointConfig(
        name="store_items",
        path="/store/{channel}/items",
        kind="offset",
    ),
    "points_leaderboard": StreamElementsEndpointConfig(
        name="points_leaderboard",
        path="/points/{channel}/top",
        kind="offset",
        data_selector="users",
        total_path="_total",
        primary_keys=["username"],
        page_size=LEADERBOARD_PAGE_SIZE,
    ),
    "points_alltime_leaderboard": StreamElementsEndpointConfig(
        name="points_alltime_leaderboard",
        path="/points/{channel}/alltime",
        kind="offset",
        data_selector="users",
        total_path="_total",
        primary_keys=["username"],
        page_size=LEADERBOARD_PAGE_SIZE,
    ),
    "bot_commands": StreamElementsEndpointConfig(
        name="bot_commands",
        path="/bot/commands/{channel}",
        kind="single",
    ),
    "bot_timers": StreamElementsEndpointConfig(
        name="bot_timers",
        path="/bot/timers/{channel}",
        kind="single",
    ),
    "channel": StreamElementsEndpointConfig(
        name="channel",
        path="/channels/me",
        kind="single",
        returns_list=False,
    ),
}

ENDPOINTS = tuple(STREAMELEMENTS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in STREAMELEMENTS_ENDPOINTS.items()
}
