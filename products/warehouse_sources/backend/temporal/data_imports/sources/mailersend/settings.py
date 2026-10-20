from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass(frozen=True)
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
    supports_append: bool = False
    # The Activity stream lives under /activity/{domain_id}; we fan out one paginated request per
    # sending domain and stamp each row with its domain_id.
    fan_out_over_domains: bool = False
    # /analytics/date returns one non-paginated object holding a `stats` array of per-day counters
    # for a required date_from/date_to window, rather than a paged list.
    analytics_by_date: bool = False
    # Activity retention tiers (days), widest first, for the date-filtered Activity endpoint.
    # MailerSend keeps email activity for 30, 7 or 1 days depending on the account's plan and
    # rejects a window reaching back further with a 422, but exposes no endpoint for the plan. The
    # sync asks for the widest window and narrows to the next tier when a request is rejected.
    window_tiers_days: tuple[int, ...] = ()
    page_size: int = 100
    should_sync_default: bool = True


_DT = IncrementalFieldType.DateTime


def _created_at_incremental_field() -> IncrementalField:
    return {"label": "created_at", "type": _DT, "field": "created_at", "field_type": _DT}


def _date_incremental_field() -> IncrementalField:
    return {"label": "date", "type": _DT, "field": "date", "field_type": _DT}


MAILERSEND_ENDPOINTS: dict[str, MailerSendEndpointConfig] = {
    # Top-level list endpoints. MailerSend exposes no server-side updated_since/created_since cursor
    # on these, so they're full refresh only (confirmed against the public API docs).
    "domains": MailerSendEndpointConfig(name="domains", path="/domains"),
    "recipients": MailerSendEndpointConfig(name="recipients", path="/recipients"),
    "templates": MailerSendEndpointConfig(name="templates", path="/templates"),
    "messages": MailerSendEndpointConfig(name="messages", path="/messages"),
    # Account-wide suppression lists (no domain_id filter). Same page-based listing as above.
    "hard_bounces": MailerSendEndpointConfig(name="hard_bounces", path="/suppressions/hard-bounces"),
    "spam_complaints": MailerSendEndpointConfig(name="spam_complaints", path="/suppressions/spam-complaints"),
    "unsubscribes": MailerSendEndpointConfig(name="unsubscribes", path="/suppressions/unsubscribes"),
    # Account-wide email counters bucketed per day. Filtered server-side by date_from/date_to, so
    # incremental re-reads from the last synced day; merge on `date` refreshes that partial day.
    # Append is off because it would add a second row for the same day on every sync.
    "analytics_by_date": MailerSendEndpointConfig(
        name="analytics_by_date",
        path="/analytics/date",
        primary_keys=["date"],
        partition_key="date",
        incremental_fields=[_date_incremental_field()],
        supports_incremental=True,
        analytics_by_date=True,
    ),
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
        supports_append=True,
        fan_out_over_domains=True,
        window_tiers_days=(30, 7, 1),
        page_size=100,
    ),
}

ENDPOINTS = tuple(MAILERSEND_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in MAILERSEND_ENDPOINTS.items()
}
