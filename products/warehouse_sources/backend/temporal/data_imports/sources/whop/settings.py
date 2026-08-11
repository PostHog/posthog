from dataclasses import dataclass

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SortMode
from products.warehouse_sources.backend.types import IncrementalField

BASE_URL = "https://api.whop.com/api/v1"

WHOP_API_KEYS_URL = "https://whop.com/dashboard/developer"

# Whop pages with Relay-style cursors (`first` + `after`). The docs publish no maximum page size,
# so stay on a conservative 100.
PAGE_SIZE = 100


@dataclass
class WhopEndpointConfig:
    path: str
    # Whether `company_id` is a required query param. The rest accept it as an optional narrowing
    # filter, which we always send so a key reaching several companies stays pinned to the one the
    # user connected.
    company_id_required: bool = False
    # Set when the endpoint's `order` enum contains `created_at`. Only then can we force a known
    # ascending page order and let the pipeline checkpoint the watermark after every batch.
    supports_created_at_order: bool = False
    # Set when the endpoint exposes a `direction` param. Endpoints with `direction` but no `order`
    # sort on an undocumented column, so we pin `direction=desc` and defer the watermark.
    supports_direction: bool = False
    # Set when the endpoint accepts the server-side `created_after` ISO 8601 filter *and* the
    # resource carries a `created_at` column for the pipeline to track.
    supports_created_after: bool = False
    partition_key: str | None = "created_at"


WHOP_ENDPOINTS: dict[str, WhopEndpointConfig] = {
    "memberships": WhopEndpointConfig(
        path="/memberships",
        supports_created_at_order=True,
        supports_direction=True,
        supports_created_after=True,
    ),
    "payments": WhopEndpointConfig(
        path="/payments",
        supports_created_at_order=True,
        supports_direction=True,
        supports_created_after=True,
    ),
    "members": WhopEndpointConfig(
        path="/members",
        supports_created_at_order=True,
        supports_direction=True,
        supports_created_after=True,
    ),
    "products": WhopEndpointConfig(
        path="/products",
        company_id_required=True,
        supports_created_at_order=True,
        supports_direction=True,
        supports_created_after=True,
    ),
    "entries": WhopEndpointConfig(
        path="/entries",
        company_id_required=True,
        supports_created_at_order=True,
        supports_direction=True,
        supports_created_after=True,
    ),
    "invoices": WhopEndpointConfig(
        path="/invoices",
        supports_created_at_order=True,
        supports_direction=True,
        supports_created_after=True,
    ),
    "refunds": WhopEndpointConfig(
        path="/refunds",
        supports_direction=True,
        supports_created_after=True,
    ),
    "disputes": WhopEndpointConfig(
        path="/disputes",
        company_id_required=True,
        supports_direction=True,
        supports_created_after=True,
    ),
    "dispute_alerts": WhopEndpointConfig(
        path="/dispute_alerts",
        company_id_required=True,
        supports_direction=True,
        supports_created_after=True,
    ),
    "setup_intents": WhopEndpointConfig(
        path="/setup_intents",
        company_id_required=True,
        supports_direction=True,
        supports_created_after=True,
    ),
    "promo_codes": WhopEndpointConfig(
        path="/promo_codes",
        company_id_required=True,
        supports_created_after=True,
    ),
    "leads": WhopEndpointConfig(
        path="/leads",
        company_id_required=True,
        supports_created_after=True,
    ),
    "experiences": WhopEndpointConfig(
        path="/experiences",
        company_id_required=True,
        supports_created_after=True,
    ),
    # `created_after` is accepted here but the resource carries no `created_at` column, so there is
    # nothing to track incrementally or partition on.
    "checkout_configurations": WhopEndpointConfig(
        path="/checkout_configurations",
        company_id_required=True,
        supports_direction=True,
        partition_key=None,
    ),
    "affiliates": WhopEndpointConfig(path="/affiliates", company_id_required=True, supports_direction=True),
    "shipments": WhopEndpointConfig(path="/shipments"),
    "company_token_transactions": WhopEndpointConfig(path="/company_token_transactions", company_id_required=True),
}

ENDPOINTS = tuple(WHOP_ENDPOINTS.keys())

# Every Whop resource we sync exposes `created_at` as an immutable ISO 8601 datetime, and
# `created_after` is the only server-side timestamp filter offered across the catalog. `/payments`
# also takes `updated_after`, but its `order` enum has no `updated_at` column, so an updated_at
# cursor could never be paired with a known page order. Incremental sync therefore tracks
# `created_at` everywhere, which does not re-surface in-place updates - webhooks cover those for the
# resources Whop emits events for.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [incremental_field("created_at")] for name, config in WHOP_ENDPOINTS.items() if config.supports_created_after
}

INCREMENTAL_ENDPOINTS = tuple(INCREMENTAL_FIELDS.keys())

# Endpoints that can only ship a merge, never an append: where the page order is undocumented we
# page newest-first and stop at the watermark, which re-yields boundary rows only a merge on `id`
# dedupes.
MERGE_ONLY_ENDPOINTS = tuple(
    name for name in INCREMENTAL_ENDPOINTS if not WHOP_ENDPOINTS[name].supports_created_at_order
)


def sort_mode_for(endpoint: str) -> SortMode:
    """The order rows actually arrive in for `endpoint`.

    Only endpoints with `created_at` in their `order` enum can be forced ascending. For the rest
    Whop documents no sort column, so we declare `desc`: the pipeline then finalizes the incremental
    watermark once, after a fully successful sync, instead of checkpointing per batch against an
    order we cannot verify.
    """
    return "asc" if WHOP_ENDPOINTS[endpoint].supports_created_at_order else "desc"


# Webhook events per schema, taken from the `WebhookEvent` enum in Whop's stable OpenAPI spec. Each
# delivery carries the full resource under `data` in the same shape the list endpoint returns, so
# webhook rows merge onto the tables the pull path fills.
SCHEMA_TO_WEBHOOK_EVENTS: dict[str, list[str]] = {
    "payments": ["payment.created", "payment.succeeded", "payment.failed", "payment.pending"],
    "memberships": [
        "membership.activated",
        "membership.deactivated",
        "membership.trial_ending_soon",
        "membership.cancel_at_period_end_changed",
    ],
    "members": ["member.created"],
    "products": [
        "product.created",
        "product.updated",
        "product.deleted",
        "product.published",
        "product.unpublished",
    ],
    "entries": ["entry.created", "entry.approved", "entry.denied", "entry.deleted"],
    "invoices": [
        "invoice.created",
        "invoice.paid",
        "invoice.past_due",
        "invoice.voided",
        "invoice.marked_uncollectible",
    ],
    "refunds": ["refund.created", "refund.updated"],
    "disputes": ["dispute.created", "dispute.updated"],
    "dispute_alerts": ["dispute_alert.created"],
    "setup_intents": ["setup_intent.requires_action", "setup_intent.succeeded", "setup_intent.canceled"],
    "shipments": ["shipment.created", "shipment.updated"],
}

WEBHOOK_SCHEMA_NAMES = tuple(SCHEMA_TO_WEBHOOK_EVENTS.keys())

ALL_WEBHOOK_EVENTS = sorted({event for events in SCHEMA_TO_WEBHOOK_EVENTS.values() for event in events})

# Schema name -> the resource prefix shared by its event types. Whop names events
# `<resource>.<action>` (e.g. `payment.succeeded`), so the hog template splits on the first dot and
# looks the prefix up in `schema_mapping`. `dispute` and `dispute_alert` stay distinct because the
# split keeps the whole prefix.
RESOURCE_TO_EVENT_PREFIX: dict[str, str] = {
    name: events[0].split(".", 1)[0] for name, events in SCHEMA_TO_WEBHOOK_EVENTS.items()
}
