from dataclasses import dataclass, field


@dataclass
class BigMailerEndpointConfig:
    name: str
    # Path under the v1 base URL. Brand-scoped endpoints carry a `{brand_id}` placeholder that the
    # transport fills in per brand while fanning out.
    path: str
    # Brand-scoped endpoints live under /brands/{brand_id}/... and must be iterated once per brand.
    # Top-level endpoints (brands, users) are account-wide and queried directly.
    brand_scoped: bool = False
    # Stable creation timestamp used for datetime partitioning. Every BigMailer object exposes
    # `created` as UNIX epoch seconds, which never changes after creation.
    partition_key: str = "created"
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Whether the table is selected for sync by default in the connection wizard.
    should_sync_default: bool = True


# BigMailer is brand-scoped: an account holds many brands and most resources hang off a brand. The
# transport lists brands once, then fans out the brand-scoped endpoints per brand, injecting
# `brand_id` into every row so the composite ["brand_id", "id"] key stays unique across the table.
#
# The API has no server-side timestamp filter on any list endpoint and cursor pagination doesn't
# accept a sort param, so every endpoint is full-refresh only (see source.py get_schemas).
_BRAND_COMPOSITE_KEY = ["brand_id", "id"]

BIGMAILER_ENDPOINTS: dict[str, BigMailerEndpointConfig] = {
    "brands": BigMailerEndpointConfig(
        name="brands",
        path="/brands",
    ),
    "users": BigMailerEndpointConfig(
        name="users",
        path="/users",
        should_sync_default=False,
    ),
    "contacts": BigMailerEndpointConfig(
        name="contacts",
        path="/brands/{brand_id}/contacts",
        brand_scoped=True,
        primary_keys=_BRAND_COMPOSITE_KEY,
    ),
    "lists": BigMailerEndpointConfig(
        name="lists",
        path="/brands/{brand_id}/lists",
        brand_scoped=True,
        primary_keys=_BRAND_COMPOSITE_KEY,
    ),
    "segments": BigMailerEndpointConfig(
        name="segments",
        path="/brands/{brand_id}/segments",
        brand_scoped=True,
        primary_keys=_BRAND_COMPOSITE_KEY,
    ),
    "fields": BigMailerEndpointConfig(
        name="fields",
        path="/brands/{brand_id}/fields",
        brand_scoped=True,
        primary_keys=_BRAND_COMPOSITE_KEY,
    ),
    "bulk_campaigns": BigMailerEndpointConfig(
        name="bulk_campaigns",
        path="/brands/{brand_id}/bulk-campaigns",
        brand_scoped=True,
        primary_keys=_BRAND_COMPOSITE_KEY,
    ),
    "transactional_campaigns": BigMailerEndpointConfig(
        name="transactional_campaigns",
        path="/brands/{brand_id}/transactional-campaigns",
        brand_scoped=True,
        primary_keys=_BRAND_COMPOSITE_KEY,
    ),
    "rss_campaigns": BigMailerEndpointConfig(
        name="rss_campaigns",
        path="/brands/{brand_id}/rss-campaigns",
        brand_scoped=True,
        primary_keys=_BRAND_COMPOSITE_KEY,
    ),
    "message_types": BigMailerEndpointConfig(
        name="message_types",
        path="/brands/{brand_id}/message-types",
        brand_scoped=True,
        primary_keys=_BRAND_COMPOSITE_KEY,
    ),
    "senders": BigMailerEndpointConfig(
        name="senders",
        path="/brands/{brand_id}/senders",
        brand_scoped=True,
        primary_keys=_BRAND_COMPOSITE_KEY,
    ),
    "templates": BigMailerEndpointConfig(
        name="templates",
        path="/brands/{brand_id}/templates",
        brand_scoped=True,
        primary_keys=_BRAND_COMPOSITE_KEY,
    ),
    "suppression_lists": BigMailerEndpointConfig(
        name="suppression_lists",
        path="/brands/{brand_id}/suppression-lists",
        brand_scoped=True,
        primary_keys=_BRAND_COMPOSITE_KEY,
    ),
}

ENDPOINTS = tuple(BIGMAILER_ENDPOINTS.keys())
