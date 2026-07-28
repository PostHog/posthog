from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField


@dataclass
class CampaignMonitorEndpointConfig:
    name: str
    # Path relative to the API base URL. May contain `{client_id}` (filled from the
    # source config), `{list_id}` (filled per-parent when fanning out over lists), or
    # `{campaign_id}` (filled per-parent when fanning out over sent campaigns).
    path: str
    primary_keys: list[str]
    # Whether the endpoint returns a paged envelope (`{"Results": [...], "NumberOfPages": N, ...}`)
    # rather than a bare JSON array.
    paginated: bool = False
    # Whether this endpoint must be fetched once per subscriber list (fan-out over the
    # client's lists). Each emitted row is annotated with its `ListID`.
    fan_out_over_lists: bool = False
    # Whether this endpoint must be fetched once per sent campaign (fan-out over the
    # client's campaigns). Each emitted row is annotated with its `CampaignID`.
    fan_out_over_campaigns: bool = False
    # Subscriber-state endpoints accept a `date` query param that filters records to those
    # added/changed at-or-after that date. We pass a very early date to fetch full history.
    uses_date_filter: bool = False
    # Stable datetime field used for datetime partitioning. Must not change over time
    # (so never `*Updated`/`*Modified` style fields).
    partition_key: Optional[str] = None
    # `orderfield` passed to paged endpoints so pagination is stable across the sync.
    order_field: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)


# Campaign Monitor (CreateSend) API v3.3 endpoints.
#
# Almost every useful endpoint is scoped to a Client ID, so the source requires one. The
# account-level `clients` endpoint is included for reference/joins.
#
# Incremental note: the subscriber-state endpoints (`active`/`unsubscribed`/`bounced`) and the
# campaign report endpoints expose a server-side `date` filter that is the canonical incremental
# mechanism for this API. It is documented but could not be verified against a live account here
# (no credentials), so every endpoint currently ships as full refresh. Enabling incremental is a
# matter of populating `incremental_fields`, flipping `supports_incremental`, and mapping the
# user's cursor value into the `date` param in `campaign_monitor.py` once verified live.
CAMPAIGN_MONITOR_ENDPOINTS: dict[str, CampaignMonitorEndpointConfig] = {
    "clients": CampaignMonitorEndpointConfig(
        name="clients",
        path="clients.json",
        primary_keys=["ClientID"],
    ),
    "campaigns": CampaignMonitorEndpointConfig(
        name="campaigns",
        path="clients/{client_id}/campaigns.json",
        primary_keys=["CampaignID"],
        partition_key="SentDate",
    ),
    "scheduled_campaigns": CampaignMonitorEndpointConfig(
        name="scheduled_campaigns",
        path="clients/{client_id}/scheduled.json",
        primary_keys=["CampaignID"],
    ),
    "draft_campaigns": CampaignMonitorEndpointConfig(
        name="draft_campaigns",
        path="clients/{client_id}/drafts.json",
        primary_keys=["CampaignID"],
    ),
    "lists": CampaignMonitorEndpointConfig(
        name="lists",
        path="clients/{client_id}/lists.json",
        primary_keys=["ListID"],
    ),
    "segments": CampaignMonitorEndpointConfig(
        name="segments",
        path="clients/{client_id}/segments.json",
        primary_keys=["SegmentID"],
    ),
    "templates": CampaignMonitorEndpointConfig(
        name="templates",
        path="clients/{client_id}/templates.json",
        primary_keys=["TemplateID"],
    ),
    "suppression_list": CampaignMonitorEndpointConfig(
        name="suppression_list",
        path="clients/{client_id}/suppressionlist.json",
        primary_keys=["EmailAddress"],
        paginated=True,
        partition_key="Date",
        order_field="date",
    ),
    "active_subscribers": CampaignMonitorEndpointConfig(
        name="active_subscribers",
        path="lists/{list_id}/active.json",
        primary_keys=["ListID", "EmailAddress"],
        paginated=True,
        fan_out_over_lists=True,
        uses_date_filter=True,
        partition_key="Date",
        order_field="date",
    ),
    "unsubscribed_subscribers": CampaignMonitorEndpointConfig(
        name="unsubscribed_subscribers",
        path="lists/{list_id}/unsubscribed.json",
        primary_keys=["ListID", "EmailAddress"],
        paginated=True,
        fan_out_over_lists=True,
        uses_date_filter=True,
        partition_key="Date",
        order_field="date",
    ),
    "bounced_subscribers": CampaignMonitorEndpointConfig(
        name="bounced_subscribers",
        path="lists/{list_id}/bounced.json",
        primary_keys=["ListID", "EmailAddress"],
        paginated=True,
        fan_out_over_lists=True,
        uses_date_filter=True,
        partition_key="Date",
        order_field="date",
    ),
    # Campaign report endpoints — one request (or paginated walk) per sent campaign. The
    # summary endpoint returns a single JSON object per campaign; the detail endpoints use the
    # standard paged envelope. Their optional `date` filter is omitted so an unfiltered request
    # returns full history.
    "campaign_summary": CampaignMonitorEndpointConfig(
        name="campaign_summary",
        path="campaigns/{campaign_id}/summary.json",
        primary_keys=["CampaignID"],
        fan_out_over_campaigns=True,
    ),
    "campaign_opens": CampaignMonitorEndpointConfig(
        name="campaign_opens",
        # A recipient can open a campaign multiple times, so the open timestamp is part of the key.
        path="campaigns/{campaign_id}/opens.json",
        primary_keys=["CampaignID", "EmailAddress", "Date"],
        paginated=True,
        fan_out_over_campaigns=True,
        partition_key="Date",
        order_field="date",
    ),
    "campaign_clicks": CampaignMonitorEndpointConfig(
        name="campaign_clicks",
        # A recipient can click several links (and the same link several times) per campaign.
        path="campaigns/{campaign_id}/clicks.json",
        primary_keys=["CampaignID", "EmailAddress", "URL", "Date"],
        paginated=True,
        fan_out_over_campaigns=True,
        partition_key="Date",
        order_field="date",
    ),
    "campaign_unsubscribes": CampaignMonitorEndpointConfig(
        name="campaign_unsubscribes",
        path="campaigns/{campaign_id}/unsubscribes.json",
        primary_keys=["CampaignID", "EmailAddress"],
        paginated=True,
        fan_out_over_campaigns=True,
        partition_key="Date",
        order_field="date",
    ),
    "campaign_bounces": CampaignMonitorEndpointConfig(
        name="campaign_bounces",
        path="campaigns/{campaign_id}/bounces.json",
        primary_keys=["CampaignID", "EmailAddress"],
        paginated=True,
        fan_out_over_campaigns=True,
        partition_key="Date",
        order_field="date",
    ),
    "campaign_spam_complaints": CampaignMonitorEndpointConfig(
        name="campaign_spam_complaints",
        path="campaigns/{campaign_id}/spam.json",
        primary_keys=["CampaignID", "EmailAddress"],
        paginated=True,
        fan_out_over_campaigns=True,
        partition_key="Date",
        order_field="date",
    ),
}

ENDPOINTS = tuple(CAMPAIGN_MONITOR_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in CAMPAIGN_MONITOR_ENDPOINTS.items()
}
