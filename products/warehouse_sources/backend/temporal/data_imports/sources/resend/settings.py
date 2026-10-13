from dataclasses import field
from typing import Any, Optional

from posthog.dataclasses import frozen


@frozen
class ResendEndpointConfig:
    name: str
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    partition_key: Optional[str] = None
    # Cursor-paginated endpoints (e.g. /emails) use `limit` + `after`. Flat endpoints
    # return the full list in a single response, so page_size is None.
    page_size: Optional[int] = None
    # Static query params sent on every request.
    params: dict[str, Any] = field(default_factory=dict)
    # For fan-out endpoints like `contacts`, names the parent endpoint we iterate to
    # resolve the path parameter, and the path parameter the parent id fills.
    parent: Optional[str] = None
    resolve_param: Optional[str] = None
    # Skip a parent whose child request 404s instead of failing the sync.
    ignore_child_404: bool = False


RESEND_ENDPOINTS: dict[str, ResendEndpointConfig] = {
    "audiences": ResendEndpointConfig(
        name="audiences",
        path="/audiences",
        partition_key="created_at",
    ),
    "broadcasts": ResendEndpointConfig(
        name="broadcasts",
        path="/broadcasts",
        partition_key="created_at",
    ),
    "domains": ResendEndpointConfig(
        name="domains",
        path="/domains",
        partition_key="created_at",
    ),
    "emails": ResendEndpointConfig(
        name="emails",
        path="/emails",
        partition_key="created_at",
        page_size=100,
    ),
    "contacts": ResendEndpointConfig(
        name="contacts",
        path="/audiences/{audience_id}/contacts",
        partition_key="created_at",
        parent="audiences",
        resolve_param="audience_id",
    ),
    "suppressions": ResendEndpointConfig(
        name="suppressions",
        path="/suppressions",
        partition_key="created_at",
        page_size=100,
    ),
    # One row per UTC day. The start date is set at request time; Resend clamps it to the plan's
    # retention window.
    "email_metrics": ResendEndpointConfig(
        name="email_metrics",
        path="/emails/metrics",
        primary_keys=["period"],
        params={"dimensions": "period", "granularity": "daily", "timezone": "UTC"},
    ),
    # The row `id` is an opaque pagination cursor, not a stable identifier, so key on the URL
    # within its broadcast.
    "broadcast_clicked_links": ResendEndpointConfig(
        name="broadcast_clicked_links",
        path="/broadcasts/{broadcast_id}/clicked-links",
        primary_keys=["_broadcast_id", "url"],
        page_size=100,
        parent="broadcasts",
        resolve_param="broadcast_id",
        ignore_child_404=True,
    ),
}


ENDPOINTS = tuple(RESEND_ENDPOINTS.keys())
