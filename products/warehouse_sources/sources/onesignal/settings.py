from typing import Literal

from products.warehouse_sources.sources.sdk import IncrementalField, frozen

BASE_URL = "https://api.onesignal.com"
INITIAL_TIME_OFFSET = "1970-01-01T00:00:00.000Z"


@frozen
class OneSignalFanout:
    parent: str
    resolve_param: str
    resolve_field: str = "id"


@frozen
class OneSignalEndpoint:
    path: str
    data_selector: str
    page_size: int
    # "time_offset" is the notifications cursor, "next_cursor" the journeys cursor.
    pagination: Literal["time_offset", "next_cursor", "offset", "single"]
    partition_key: str | None
    app_id_in_query: bool = False
    primary_keys: tuple[str, ...] = ("id",)
    incremental_fields: tuple[IncrementalField, ...] = ()
    fanout: OneSignalFanout | None = None


# None of these endpoints has a server-side update filter, so each table is a full refresh.
# Full refresh also updates changing message delivery totals and journey stats.
ONESIGNAL_ENDPOINTS: dict[str, OneSignalEndpoint] = {
    "notifications": OneSignalEndpoint(
        path="/notifications",
        data_selector="notifications",
        page_size=50,
        pagination="time_offset",
        partition_key="queued_at",
        app_id_in_query=True,
    ),
    "segments": OneSignalEndpoint(
        path="/apps/{app_id}/segments",
        data_selector="segments",
        page_size=300,
        pagination="offset",
        partition_key="created_at",
    ),
    "templates": OneSignalEndpoint(
        path="/templates",
        data_selector="templates",
        page_size=50,
        pagination="offset",
        partition_key="created_at",
        app_id_in_query=True,
    ),
    "journeys": OneSignalEndpoint(
        path="/apps/{app_id}/journeys",
        data_selector="journeys",
        page_size=50,
        pagination="next_cursor",
        partition_key="created_at",
    ),
    "journey_stats": OneSignalEndpoint(
        path="/apps/{app_id}/journeys/{journey_id}/stats",
        data_selector="$",
        page_size=50,
        pagination="single",
        partition_key=None,
        fanout=OneSignalFanout(parent="journeys", resolve_param="journey_id"),
    ),
}
