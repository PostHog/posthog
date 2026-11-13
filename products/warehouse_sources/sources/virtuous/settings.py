from dataclasses import field
from typing import Any, Literal

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType, frozen

VIRTUOUS_BASE_URL = "https://api.virtuoussoftware.com"
# Documented maximum `take` for the list and query endpoints.
PAGE_SIZE = 1000
# The full-detail queries carry nested individuals, designations and custom fields per row, and the
# docs warn that large takes can time out, so they ask for smaller pages.
FULL_DETAIL_PAGE_SIZE = 500
REQUEST_TIMEOUT_SECONDS = 120

# Query condition name and operator from the Virtuous `QueryOptions` endpoints.
LAST_MODIFIED_PARAMETER = "Last Modified Date"
ON_OR_AFTER_OPERATOR = "OnOrAfter"
MODIFIED_FIELD = "modifiedDateTimeUtc"


@frozen
class VirtuousEndpointConfig:
    name: str
    path: str
    method: Literal["GET", "POST"] = "POST"
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # POST body for the request. Query endpoints get `sortBy`/`descending` added on top.
    request_body: dict[str, Any] = field(default_factory=dict)
    # True for the `/Query` endpoints that take `groups` of conditions and a sort.
    is_query: bool = True
    # The endpoint accepts a "Last Modified Date" condition and returns `modifiedDateTimeUtc`.
    supports_incremental: bool = False
    partition_key: str | None = None
    page_size: int = PAGE_SIZE


def _query(
    name: str,
    path: str,
    *,
    primary_keys: list[str] | None = None,
    incremental: bool = True,
    partition_key: str | None = "createDateTimeUtc",
    page_size: int = PAGE_SIZE,
    request_body: dict[str, Any] | None = None,
) -> VirtuousEndpointConfig:
    return VirtuousEndpointConfig(
        name=name,
        path=path,
        primary_keys=primary_keys or ["id"],
        request_body=request_body or {},
        supports_incremental=incremental,
        partition_key=partition_key,
        page_size=page_size,
    )


ENDPOINTS: dict[str, VirtuousEndpointConfig] = {
    config.name: config
    for config in (
        _query(
            "contacts",
            "/api/Contact/Query/FullContact",
            page_size=FULL_DETAIL_PAGE_SIZE,
            request_body={"includeArchived": True},
        ),
        _query("contact_individuals", "/api/ContactIndividual/Query"),
        _query("contact_notes", "/api/ContactNote/Query"),
        _query("gifts", "/api/Gift/Query/FullGift", page_size=FULL_DETAIL_PAGE_SIZE),
        # Gift designations have no modified timestamp, and `createDate` is a display string.
        _query("gift_designations", "/api/GiftDesignation/Query", incremental=False, partition_key=None),
        _query("gift_asks", "/api/GiftAsk/Query"),
        _query("planned_gifts", "/api/PlannedGift/Query"),
        _query("pledges", "/api/v2/Pledge/Query"),
        _query("recurring_gifts", "/api/RecurringGift/Query"),
        _query("premiums", "/api/Premium/Query"),
        _query("campaigns", "/api/Campaign/Query", primary_keys=["campaignId"]),
        _query("projects", "/api/Project/Query"),
        _query("events", "/api/Event/Query"),
        _query("event_attendees", "/api/EventAttendee/Query"),
        _query("grants", "/api/Grant/Query"),
        _query("tasks", "/api/Task/Query", incremental=False, partition_key=None),
        VirtuousEndpointConfig(name="tags", path="/api/Tag", method="GET", is_query=False),
        VirtuousEndpointConfig(name="organization_groups", path="/api/OrganizationGroup", method="GET", is_query=False),
        # An empty search term matches every segment.
        VirtuousEndpointConfig(
            name="segments", path="/api/Segment/Search", is_query=False, request_body={"search": ""}
        ),
    )
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [
        {
            "label": MODIFIED_FIELD,
            "type": IncrementalFieldType.DateTime,
            "field": MODIFIED_FIELD,
            "field_type": IncrementalFieldType.DateTime,
        }
    ]
    for name, config in ENDPOINTS.items()
    if config.supports_incremental
}
