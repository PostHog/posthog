from dataclasses import field

from products.warehouse_sources.sources.sdk import IncrementalField, frozen

API_VERSION = "v6.0"
REQUEST_TIMEOUT = (10, 30)
CUSTOM_FIELDS_UNSUPPORTED_ERROR = (
    "Your Ghost site does not support member custom fields. Update Ghost, or deselect the member_custom_fields table."
)


@frozen
class GhostEndpoint:
    description: str
    params: dict[str, str] = field(default_factory=dict)
    paginated: bool = True
    primary_keys: tuple[str, ...] = ("id",)
    partition_key: str | None = "created_at"
    path: str | None = None
    data_selector: str | None = None
    # Shown when the route returns 404 because the Ghost site is older than the endpoint.
    not_found_error: str | None = None


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
    "labels": GhostEndpoint(
        description="Member labels used for segmentation, with member counts.",
        params={"include": "count.members"},
    ),
    # The custom fields route has no pagination and returns only active fields unless the filter asks for archived ones.
    "member_custom_fields": GhostEndpoint(
        description="Custom member field definitions, including archived fields.",
        params={"filter": "status:[active,archived]"},
        paginated=False,
        primary_keys=("key",),
        path="members/metafields/custom/",
        data_selector="members_metafields",
        not_found_error=CUSTOM_FIELDS_UNSUPPORTED_ERROR,
    ),
    "roles": GhostEndpoint(description="Staff user roles.", paginated=False),
}

# Timestamp filters need verification against a live account before incremental sync can safely use them.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
