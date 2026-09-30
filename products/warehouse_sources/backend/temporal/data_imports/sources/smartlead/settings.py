from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField

BASE_URL = "https://server.smartlead.ai/api/v1"

# Leads and email accounts cap `limit` at 100. Statistics accepts up to 1000, but its rows carry
# full email subject/body HTML, so the shared 100 keeps page memory bounded.
PAGE_SIZE = 100

# Every endpoint syncs as full refresh. Smartlead documents server-side time filters on two list
# endpoints (`created_at_gt` on campaign leads, `sent_time_start_date` on campaign statistics),
# but neither filter has been verified against a live account and neither endpoint documents its
# sort order, so an ascending watermark cannot be trusted. Enable incremental only after a live
# smoke test proves the filter is honored and the response order is known.


# Mutable by choice, not oversight: instances flow into `build_dependent_resource`'s
# `endpoint_configs: Mapping[str, FanoutEndpointLike]`, and mypy treats a frozen dataclass's
# fields as read-only, which is incompatible with that Protocol's plain (read-write) attributes.
@dataclass(frozen=False)
class SmartleadEndpointConfig:
    name: str
    # Path under /api/v1. The account-level list endpoints are documented with a trailing slash.
    path: str
    # "offset": offset/limit pagination terminated by a short page. "single": the endpoint returns
    # the whole collection (or one object) in a single response and takes no pagination params.
    pagination: Literal["offset", "single"] = "single"
    # Root key of the row list in the JSON body. None means the body is the row list itself.
    data_selector: Optional[str] = None
    # False only for endpoints whose body is a single JSON object (campaign analytics), which is
    # wrapped into a one-row page instead of being validated as a list.
    expects_list: bool = True
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable creation-time field for datetime partitioning. Never an updated_at-style field.
    partition_key: Optional[str] = "created_at"
    # Response fields dropped before rows reach the warehouse. Smartlead returns connected
    # mailbox SMTP/IMAP passwords (base64-encoded) on email accounts; credentials must never
    # land in a synced table.
    redact_fields: tuple[str, ...] = ()
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # The cursor field the fan-out helper would bind a server filter to. Only read for fan-out
    # children, and only once an endpoint advertises incremental fields.
    default_incremental_field: Optional[str] = None
    # Set for per-campaign resources that hang off the account-level campaign list.
    fanout: Optional[DependentEndpointConfig] = None
    page_size: int = PAGE_SIZE


def _campaign_fanout() -> DependentEndpointConfig:
    # Child rows don't consistently carry their campaign id, so inject the parent's `id` as
    # `campaign_id` on every child row; composite primary keys rely on it.
    return DependentEndpointConfig(
        parent_name="campaigns",
        resolve_param="campaign_id",
        resolve_field="id",
        include_from_parent=["id"],
        parent_field_renames={"id": "campaign_id"},
    )


SMARTLEAD_ENDPOINTS: dict[str, SmartleadEndpointConfig] = {
    # Returns the full campaign list as a bare array, newest first, with no pagination params.
    "campaigns": SmartleadEndpointConfig(
        name="campaigns",
        path="/campaigns/",
    ),
    # Bare array of sequence steps per campaign. The docs' JSON example shows a `data` envelope
    # but the same page states "Response Format: array"; the array shape matches the live API's
    # historical behavior. `data_selector_required` fails loud if the shape ever changes.
    "campaign_sequences": SmartleadEndpointConfig(
        name="campaign_sequences",
        path="/campaigns/{campaign_id}/sequences",
        primary_keys=["campaign_id", "id"],
        fanout=_campaign_fanout(),
    ),
    "campaign_leads": SmartleadEndpointConfig(
        name="campaign_leads",
        path="/campaigns/{campaign_id}/leads",
        pagination="offset",
        data_selector="data",
        # `campaign_lead_map_id` identifies the lead-to-campaign mapping row. Keep the campaign id
        # in the key anyway so a duplicate can never span campaigns.
        primary_keys=["campaign_id", "campaign_lead_map_id"],
        fanout=_campaign_fanout(),
    ),
    "campaign_statistics": SmartleadEndpointConfig(
        name="campaign_statistics",
        path="/campaigns/{campaign_id}/statistics",
        pagination="offset",
        data_selector="data",
        # `stats_id` identifies one sent email. The current docs list rows without it, but the
        # live API returns it; harmless if absent since this table only syncs as full refresh.
        primary_keys=["campaign_id", "stats_id"],
        # Statistics rows are send events; the send time never changes.
        partition_key="sent_time",
        fanout=_campaign_fanout(),
    ),
    # One aggregate metrics object per campaign. The row's identity is the injected campaign id
    # because the response body's own id field differs between docs and the live API.
    "campaign_analytics": SmartleadEndpointConfig(
        name="campaign_analytics",
        path="/campaigns/{campaign_id}/analytics",
        expects_list=False,
        primary_keys=["campaign_id"],
        partition_key=None,
        fanout=_campaign_fanout(),
    ),
    "email_accounts": SmartleadEndpointConfig(
        name="email_accounts",
        path="/email-accounts/",
        pagination="offset",
        redact_fields=("password", "imap_password"),
    ),
    # Whitelabel client sub-accounts. The docs' example shows an `{ok, data}` envelope, but the
    # live API has historically returned a bare array; `data_selector_required` fails loud
    # rather than syncing a garbage row if the envelope shape is what ships.
    "clients": SmartleadEndpointConfig(
        name="clients",
        path="/client/",
    ),
}

ENDPOINTS = tuple(SMARTLEAD_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SMARTLEAD_ENDPOINTS.items()
}
