from dataclasses import dataclass, field


@dataclass
class JudgeMeReviewsEndpointConfig:
    name: str
    path: str
    # Judge.me wraps each list response in a key named after the resource
    # (e.g. `{"current_page": 1, "per_page": 10, "reviews": [...]}`), so the row list
    # key varies per endpoint and is stored here.
    list_key: str
    # Judge.me internal IDs are unique within a shop, and one source is bound to one shop,
    # so `id` is a safe primary key for every endpoint.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


# Judge.me REST API list endpoints. All are full refresh only: the list endpoints expose no
# documented server-side timestamp filter (the reviews index only accepts per_page, page,
# reviewer_id, product_id, and rating), so there is no genuine incremental cursor to advance
# (a client-side scan of every page would cost the same as a full refresh — see the skill).
JUDGEME_REVIEWS_ENDPOINTS: dict[str, JudgeMeReviewsEndpointConfig] = {
    "reviews": JudgeMeReviewsEndpointConfig(name="reviews", path="/reviews", list_key="reviews"),
    # `/products` is absent from the current OpenAPI spec but is documented in Judge.me's legacy
    # API docs and exists on the live API (401 with bad credentials, vs 404 for unknown paths).
    # It maps Judge.me internal product IDs to external (Shopify) products, which is needed to
    # join reviews to store catalog data.
    "products": JudgeMeReviewsEndpointConfig(name="products", path="/products", list_key="products"),
}

ENDPOINTS = tuple(JUDGEME_REVIEWS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[dict[str, str]]] = {}
