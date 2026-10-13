from dataclasses import field

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField

API_VERSION = "v6.0"
REQUEST_TIMEOUT = (10, 30)


@frozen
class GhostEndpoint:
    description: str
    params: dict[str, str] = field(default_factory=dict)
    paginated: bool = True
    primary_keys: tuple[str, ...] = ("id",)
    partition_key: str | None = "created_at"


ENDPOINTS: dict[str, GhostEndpoint] = {
    "members": GhostEndpoint(
        description="Members, subscriptions, labels, newsletter subscriptions, and email engagement totals.",
        params={"include": "tiers"},
    ),
    "posts": GhostEndpoint(
        description="Published, draft, and scheduled posts with authors, tags, and newsletter delivery statistics.",
        params={"include": "tags,authors,email,newsletter", "formats": "html,lexical"},
    ),
    "pages": GhostEndpoint(
        description="Static pages with content, authors, and tags.",
        params={"include": "tags,authors", "formats": "html,lexical"},
    ),
    "tiers": GhostEndpoint(
        description="Membership tiers with monthly prices, yearly prices, and benefits.",
        params={"include": "monthly_price,yearly_price,benefits"},
    ),
    # Offers ignore pagination parameters and omit creation timestamps from their response.
    "offers": GhostEndpoint(
        description="Subscription discounts and redemption totals.", paginated=False, partition_key=None
    ),
    "newsletters": GhostEndpoint(description="Newsletter settings and sender details."),
    "tags": GhostEndpoint(description="Content tags, including internal tags."),
    "users": GhostEndpoint(description="Staff users and author profiles."),
}

# Timestamp filters need verification against a live account before incremental sync can safely use them.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
