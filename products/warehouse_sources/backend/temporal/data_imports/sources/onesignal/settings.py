from typing import Literal

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField

BASE_URL = "https://api.onesignal.com"
INITIAL_TIME_OFFSET = "1970-01-01T00:00:00.000Z"


@frozen
class OneSignalEndpoint:
    path: str
    data_selector: str
    page_size: int
    pagination: Literal["cursor", "offset"]
    partition_key: str
    primary_keys: tuple[str, ...] = ("id",)
    incremental_fields: tuple[IncrementalField, ...] = ()


# The time filter is unverified with an account. Full refresh also updates changing message delivery totals.
ONESIGNAL_ENDPOINTS: dict[str, OneSignalEndpoint] = {
    "notifications": OneSignalEndpoint(
        path="/notifications",
        data_selector="notifications",
        page_size=50,
        pagination="cursor",
        partition_key="queued_at",
    ),
    "segments": OneSignalEndpoint(
        path="/apps/{app_id}/segments",
        data_selector="segments",
        page_size=300,
        pagination="offset",
        partition_key="created_at",
    ),
}
