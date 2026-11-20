from dataclasses import dataclass, field
from datetime import date
from typing import Literal, Optional

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType

WISTIA_BASE_URL = "https://api.wistia.com/modern"
WISTIA_API_VERSION = "2026-09"
WISTIA_API_VERSION_HEADER = "X-Wistia-API-Version"

# Wistia caps `per_page` at 100 on every list endpoint.
PAGE_SIZE = 100

# Account stats by date has no pagination, so a full refresh walks the history in yearly windows.
ACCOUNT_STATS_HISTORY_START = date(2010, 1, 1)
ACCOUNT_STATS_WINDOW_DAYS = 365


@dataclass(frozen=True)
class WistiaEndpointConfig:
    name: str
    path: str
    primary_keys: list[str]
    params: dict[str, str] = field(default_factory=dict)
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # A creation timestamp that never changes, for datetime partitioning.
    partition_key: Optional[str] = None
    partition_format: Literal["month", "week"] = "month"
    should_sync_default: bool = True
    description: Optional[str] = None
    # Fan-out: `path` holds a `{parent_id}` placeholder, filled from the parent's `hashed_id`.
    # `parent_key` is the child column that holds the parent id, so the primary key stays unique.
    parent: Optional[str] = None
    parent_key: Optional[str] = None
    # The child endpoint returns one object per parent, not a list.
    child_is_single_object: bool = False


WISTIA_ENDPOINTS: dict[str, WistiaEndpointConfig] = {
    "medias": WistiaEndpointConfig(
        name="medias",
        path="/medias",
        primary_keys=["hashed_id"],
        params={"sort_by": "created", "sort_direction": "1"},
        partition_key="created",
    ),
    "folders": WistiaEndpointConfig(
        name="folders",
        path="/folders",
        primary_keys=["hashed_id"],
        params={"sort_by": "created", "sort_direction": "1"},
        partition_key="created",
    ),
    "subfolders": WistiaEndpointConfig(
        name="subfolders",
        path="/folders/{parent_id}/subfolders",
        primary_keys=["folder_hashed_id", "hashed_id"],
        params={"sort_by": "id", "sort_direction": "1"},
        parent="folders",
        parent_key="folder_hashed_id",
        description="Full refresh only. Reads the subfolders of every folder.",
    ),
    "tags": WistiaEndpointConfig(
        name="tags",
        path="/tags",
        primary_keys=["name"],
        params={"sort_by": "created", "sort_direction": "1"},
        partition_key="created_at",
    ),
    "captions": WistiaEndpointConfig(
        name="captions",
        path="/captions",
        primary_keys=["media_id", "id"],
        params={"sort_by": "id", "sort_direction": "1"},
    ),
    "channels": WistiaEndpointConfig(
        name="channels",
        path="/channels",
        primary_keys=["hashed_id"],
        params={"sort_by": "created", "sort_direction": "1"},
        partition_key="created",
    ),
    "channel_episodes": WistiaEndpointConfig(
        name="channel_episodes",
        path="/channel_episodes",
        primary_keys=["hashed_id"],
        params={"sort_by": "created", "sort_direction": "1"},
        partition_key="created",
    ),
    # Webinars are not on every Wistia plan, and the API returns 403 for accounts without them.
    "webinars": WistiaEndpointConfig(
        name="webinars",
        path="/webinars",
        primary_keys=["hashed_id"],
        params={"sort_by": "created", "sort_direction": "1"},
        partition_key="created_at",
        should_sync_default=False,
        description="Needs a Wistia plan that includes webinars.",
    ),
    # The Stats API documents no sort parameter for visitors and events.
    "visitors": WistiaEndpointConfig(
        name="visitors",
        path="/stats/visitors",
        primary_keys=["visitor_key"],
        partition_key="created_at",
    ),
    "events": WistiaEndpointConfig(
        name="events",
        path="/stats/events",
        primary_keys=["event_key"],
        incremental_fields=[
            {
                "label": "received_at",
                "type": IncrementalFieldType.DateTime,
                "field": "received_at",
                "field_type": IncrementalFieldType.DateTime,
            }
        ],
        partition_key="received_at",
        partition_format="week",
        description="Wistia keeps events for 2 years.",
    ),
    "media_stats": WistiaEndpointConfig(
        name="media_stats",
        path="/stats/medias/{parent_id}",
        primary_keys=["media_hashed_id"],
        parent="medias",
        parent_key="media_hashed_id",
        child_is_single_object=True,
        should_sync_default=False,
        description="Full refresh only. Makes one request for each media.",
    ),
    "account_stats_by_date": WistiaEndpointConfig(
        name="account_stats_by_date",
        path="/stats/account/by_date",
        primary_keys=["date"],
        incremental_fields=[
            {
                "label": "date",
                "type": IncrementalFieldType.Date,
                "field": "date",
                "field_type": IncrementalFieldType.Date,
            }
        ],
        partition_key="date",
    ),
}

ENDPOINTS = tuple(WISTIA_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in WISTIA_ENDPOINTS.items() if config.incremental_fields
}
