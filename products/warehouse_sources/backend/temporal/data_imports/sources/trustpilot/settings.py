from dataclasses import dataclass, field
from typing import Literal, Optional

# Trustpilot's public Business Units API serves three shapes from the one connection:
#
#   - "single":          `/business-units/{id}` returns one business unit object, not a list.
#   - "paginated":       a `page`/`perPage` list wrapped under a body key (`reviews`,
#                        `productReviews`), walked forward a page at a time.
#   - "review_replies":  the company replies embedded in each service review. Trustpilot has no
#                        public list-replies endpoint, so this walks the same service-reviews list
#                        and lifts each review's `companyReply` into its own row.
EndpointKind = Literal["single", "paginated", "review_replies"]

# Trustpilot caps these list endpoints at 100 results per page.
MAX_PAGE_SIZE = 100


@dataclass
class TrustpilotEndpointConfig:
    name: str
    kind: EndpointKind
    primary_keys: list[str]
    # API path, formatted with the configured `{business_unit_id}`.
    path: str
    # Body key holding the array of rows for a "paginated"/"review_replies" endpoint.
    data_key: str = ""
    # Extra query params sent on every page request.
    params: dict[str, str] = field(default_factory=dict)
    # Stable creation-style field to partition by — never an updated/modified field.
    partition_key: Optional[str] = None


TRUSTPILOT_ENDPOINTS: dict[str, TrustpilotEndpointConfig] = {
    # The configured business unit's public profile: display name, website, TrustScore and review
    # counts. A single object, so there is nothing to paginate or partition.
    "business_units": TrustpilotEndpointConfig(
        name="business_units",
        kind="single",
        primary_keys=["id"],
        path="/business-units/{business_unit_id}",
    ),
    # Service (company) reviews left on the business unit's Trustpilot profile.
    "service_reviews": TrustpilotEndpointConfig(
        name="service_reviews",
        kind="paginated",
        primary_keys=["id"],
        path="/business-units/{business_unit_id}/reviews",
        data_key="reviews",
        partition_key="createdAt",
    ),
    # Reviews of individual products sold by the business unit.
    "product_reviews": TrustpilotEndpointConfig(
        name="product_reviews",
        kind="paginated",
        primary_keys=["id"],
        path="/product-reviews/business-units/{business_unit_id}",
        data_key="productReviews",
        partition_key="createdAt",
    ),
    # The business's public replies to its service reviews, keyed on the review they answer. Lifted
    # from each review's embedded `companyReply`, since Trustpilot exposes no list-replies endpoint.
    "review_replies": TrustpilotEndpointConfig(
        name="review_replies",
        kind="review_replies",
        primary_keys=["review_id"],
        path="/business-units/{business_unit_id}/reviews",
        data_key="reviews",
        partition_key="createdAt",
    ),
}

ENDPOINTS = tuple(TRUSTPILOT_ENDPOINTS.keys())

# The public Business Units API exposes no server-side timestamp filter on any of these endpoints, so
# every table is a full refresh merged on its unique primary key — none advertise incremental fields.
INCREMENTAL_FIELDS: dict[str, list] = {name: [] for name in ENDPOINTS}
