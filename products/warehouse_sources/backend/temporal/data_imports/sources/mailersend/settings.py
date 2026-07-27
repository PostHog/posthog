from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class MailerSendEndpointConfig:
    name: str
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Partition by a STABLE creation timestamp so partitions never rewrite (never updated_at).
    partition_key: Optional[str] = "created_at"
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Only true where MailerSend exposes a genuine server-side timestamp filter (the Activity
    # endpoint's date_from/date_to). Everything else is full refresh — the list endpoints have no
    # updated_since/created_since cursor.
    supports_incremental: bool = False
    # The Activity stream lives under /activity/{domain_id}; we fan out one paginated request per
    # sending domain and stamp each row with its domain_id.
    fan_out_over_domains: bool = False
    # First-sync lookback (days) for date-filtered endpoints. Capped to MailerSend's activity data
    # retention window (1-30 days depending on plan); 30 is the widest a request can ask for.
    default_lookback_days: Optional[int] = None
    page_size: int = 100
    should_sync_default: bool = True


_DT = IncrementalFieldType.DateTime


def _created_at_incremental_field() -> IncrementalField:
    return {"label": "created_at", "type": _DT, "field": "created_at", "field_type": _DT}


MAILERSEND_ENDPOINTS: dict[str, MailerSendEndpointConfig] = {
    # Top-level list endpoints. MailerSend exposes no server-side updated_since/created_since cursor
    # on these, so they're full refresh only (confirmed against the public API docs).
    "domains": MailerSendEndpointConfig(name="domains", path="/domains"),
    "recipients": MailerSendEndpointConfig(name="recipients", path="/recipients"),
    "templates": MailerSendEndpointConfig(name="templates", path="/templates"),
    "messages": MailerSendEndpointConfig(name="messages", path="/messages"),
    # Email activity events (sent, delivered, opened, clicked, bounced, ...). The endpoint requires a
    # domain_id path segment and a date_from/date_to window, so we fan out over every sending domain
    # and filter server-side on created_at. Incremental with merge upsert: the date window advances to
    # the last-seen created_at, and merge dedupes any boundary overlap so re-fetches are harmless.
    "activity": MailerSendEndpointConfig(
        name="activity",
        path="/activity/{domain_id}",
        primary_keys=["domain_id", "id"],
        partition_key="created_at",
        incremental_fields=[_created_at_incremental_field()],
        supports_incremental=True,
        fan_out_over_domains=True,
        default_lookback_days=30,
        page_size=100,
    ),
}

ENDPOINTS = tuple(MAILERSEND_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in MAILERSEND_ENDPOINTS.items()
}
