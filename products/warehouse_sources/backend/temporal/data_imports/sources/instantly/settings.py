from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

BASE_URL = "https://api.instantly.ai"
API_VERSION = "v2"

# Most list endpoints cap `limit` at 100.
DEFAULT_PAGE_SIZE = 100

# GET /api/v2/emails is rate-limited to 20 requests/minute (other endpoints have looser,
# unpublished limits), so the emails stream self-throttles between pages.
EMAILS_REQUEST_INTERVAL_SECONDS = 3.0

# Webhook-fed event stream (no pull API — Instantly webhooks deliver event notifications,
# not full objects, so they get their own table instead of merging into the pull tables).
WEBHOOK_EVENTS_ENDPOINT = "webhook_events"
# All webhook deliveries route to the single webhook_events schema under this mapping key.
WEBHOOK_ROUTING_KEY = "event"


@dataclass
class InstantlyEndpointConfig:
    name: str
    # Path under https://api.instantly.ai/api/v2.
    path: str
    method: Literal["GET", "POST"] = "GET"
    # "cursor": limit/starting_after pagination with a next_starting_after cursor in the body
    # (the leads endpoint carries both in the POST JSON body instead of the query string).
    # "single": one unpaginated response.
    pagination: Literal["cursor", "single"] = "cursor"
    # Where the row list lives in the response body; None means the body is a bare JSON array.
    data_selector: Optional[str] = "items"
    # Static request params (query string for GET, JSON body for POST).
    params: dict[str, Any] = field(default_factory=dict)
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation-time field for datetime partitioning. Never an updated_at-style field.
    partition_key: Optional[str] = "timestamp_created"
    # Only emails exposes a server-side timestamp filter (min_timestamp_created + sort_order=asc).
    supports_incremental: bool = False
    description: Optional[str] = None


INSTANTLY_ENDPOINTS: dict[str, InstantlyEndpointConfig] = {
    "campaigns": InstantlyEndpointConfig(
        name="campaigns",
        path="/campaigns",
        description="Email outreach campaigns with their schedules, sequences, and sending settings.",
    ),
    "accounts": InstantlyEndpointConfig(
        name="accounts",
        path="/accounts",
        # Accounts have no `id` field — the mailbox email address is the identifier.
        primary_keys=["email"],
        description="Sending email accounts connected to the workspace, including warmup status and limits.",
    ),
    "leads": InstantlyEndpointConfig(
        name="leads",
        # Deliberate API deviation: listing leads is POST with a JSON body because the filter
        # arguments are too complex for query params.
        path="/leads/list",
        method="POST",
        description="Leads across campaigns and lead lists, with contact details and engagement counts.",
    ),
    "emails": InstantlyEndpointConfig(
        name="emails",
        path="/emails",
        # sort_order=asc keeps arrival order matching sort_mode="asc" so the incremental
        # watermark can checkpoint safely (the API defaults to newest-first).
        params={"sort_order": "asc"},
        supports_incremental=True,
        description="Sent and received emails from campaigns and the unified inbox (Unibox).",
    ),
    "lead_lists": InstantlyEndpointConfig(
        name="lead_lists",
        path="/lead-lists",
        description="Lead lists used to organize leads outside campaigns.",
    ),
    "lead_labels": InstantlyEndpointConfig(
        name="lead_labels",
        path="/lead-labels",
        description="Custom lead interest labels configured in the workspace.",
    ),
    "custom_tags": InstantlyEndpointConfig(
        name="custom_tags",
        path="/custom-tags",
        description="Custom tags that can be assigned to campaigns and accounts.",
    ),
    "campaign_analytics": InstantlyEndpointConfig(
        name="campaign_analytics",
        path="/campaigns/analytics",
        pagination="single",
        data_selector=None,
        primary_keys=["campaign_id"],
        partition_key=None,
        description="Aggregate per-campaign analytics: sends, opens, replies, clicks, bounces, and opportunities.",
    ),
    "campaign_daily_analytics": InstantlyEndpointConfig(
        name="campaign_daily_analytics",
        path="/campaigns/analytics/daily",
        pagination="single",
        data_selector=None,
        primary_keys=["date"],
        partition_key=None,
        description="Workspace-wide daily campaign analytics: sends, opens, replies, and clicks per day.",
    ),
}

ENDPOINTS = tuple(INSTANTLY_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    "emails": [incremental_field("timestamp_created")],
}
