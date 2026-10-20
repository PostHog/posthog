from dataclasses import field
from typing import Literal

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField

SEQUENZY_BASE_URL = "https://api.sequenzy.com/api/v1"


@frozen
class SequenzyEndpointConfig:
    name: str
    path: str
    # Key of the row array in the response envelope ({"success": true, "<selector>": [...]}).
    data_selector: str
    pagination: Literal["cursor", "offset", "page", "single_page"]
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    partition_key: str | None = None
    page_size: int | None = None
    params: dict[str, str | int] = field(default_factory=dict)


# Sequenzy paginates each collection differently: subscribers use an opaque cursor
# (`pagination.nextCursor`), campaigns and sequences use limit/offset, per-email metrics use
# page numbers, and the small definition collections (tags, lists, segments) return the whole
# collection in one response. Subscribers, campaigns, and sequences are returned newest-first
# with no way to request ascending order, hence sort_mode="desc" in sequenzy.py.
ENDPOINTS_CONFIG: dict[str, SequenzyEndpointConfig] = {
    "subscribers": SequenzyEndpointConfig(
        name="subscribers",
        path="/subscribers",
        data_selector="subscribers",
        pagination="cursor",
        page_size=1000,
        # `status=all` disables the default status filter so unsubscribed and bounced
        # contacts sync too. `includeTotal=false` skips the total-count query the API
        # otherwise runs for the first (cursorless) request.
        params={"status": "all", "includeTotal": "false"},
        partition_key="createdAt",
    ),
    "tags": SequenzyEndpointConfig(
        name="tags",
        path="/tags",
        data_selector="tags",
        pagination="single_page",
    ),
    "lists": SequenzyEndpointConfig(
        name="lists",
        path="/lists",
        data_selector="lists",
        pagination="single_page",
    ),
    "segments": SequenzyEndpointConfig(
        name="segments",
        path="/segments",
        data_selector="segments",
        pagination="single_page",
    ),
    "campaigns": SequenzyEndpointConfig(
        name="campaigns",
        path="/campaigns",
        data_selector="campaigns",
        pagination="offset",
        page_size=100,
        partition_key="createdAt",
    ),
    "sequences": SequenzyEndpointConfig(
        name="sequences",
        path="/sequences",
        data_selector="sequences",
        pagination="offset",
        page_size=100,
        partition_key="createdAt",
    ),
    "email_metrics": SequenzyEndpointConfig(
        name="email_metrics",
        path="/metrics/emails",
        data_selector="emails",
        pagination="page",
        page_size=500,
        # The default sort is `sent` desc, which reshuffles rows between pages as counts
        # move mid-sync. Name order is the most stable sort the endpoint offers.
        params={"sort": "name", "order": "asc"},
        # `emailId` is a campaign ID for campaign rows and an automation node ID for
        # sequence-step rows; the composite key guards against a collision across the
        # two ID namespaces.
        primary_keys=["emailType", "emailId"],
    ),
}

ENDPOINTS = tuple(ENDPOINTS_CONFIG.keys())

# The API exposes no server-side created/updated timestamp filter on any list endpoint
# (subscribers only filter on `unsubscribedAt`, which covers opted-out contacts alone),
# so every endpoint is full-refresh only.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
