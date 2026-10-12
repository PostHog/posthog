from dataclasses import dataclass
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField


@dataclass
class CustomerlyEndpointConfig:
    name: str
    path: str
    # Key the list of objects is nested under in the response body. `None` means the
    # `data` payload is the list itself (e.g. knowledge base collections/articles).
    data_key: Optional[str] = None
    primary_key: str = "crmhero_user_id"
    paginated: bool = False
    # Stable creation-time field used for datetime partitioning (UNIX epoch seconds).
    # Never an updated_at-style field, which would rewrite partitions on every sync.
    partition_key: Optional[str] = None
    # Set when rows are fetched per knowledge base collection (parent fan-out).
    fan_out_by_collection: bool = False


# The Customerly public API exposes no server-side timestamp filter (`since` /
# `updated_after`) on any list endpoint, so every table is full refresh. Pagination is
# page-number based (`page` starting at 0, `per_page`) on the users/leads/articles lists;
# tags and knowledge base collections return the full list in one response.
CUSTOMERLY_ENDPOINTS: dict[str, CustomerlyEndpointConfig] = {
    "users": CustomerlyEndpointConfig(
        name="users",
        path="/users/list",
        data_key="users",
        primary_key="crmhero_user_id",
        paginated=True,
        partition_key="first_seen_at",
    ),
    "leads": CustomerlyEndpointConfig(
        name="leads",
        path="/leads/list",
        data_key="leads",
        primary_key="crmhero_user_id",
        paginated=True,
        partition_key="first_seen_at",
    ),
    "tags": CustomerlyEndpointConfig(
        name="tags",
        path="/tags",
        primary_key="name",
    ),
    "knowledge_base_collections": CustomerlyEndpointConfig(
        name="knowledge_base_collections",
        path="/knowledge/collections",
        primary_key="knowledge_base_collection_id",
    ),
    "knowledge_base_articles": CustomerlyEndpointConfig(
        name="knowledge_base_articles",
        path="/knowledge/articles/",
        primary_key="knowledge_base_article_id",
        paginated=True,
        partition_key="created_at",
        fan_out_by_collection=True,
    ),
}

ENDPOINTS = tuple(CUSTOMERLY_ENDPOINTS.keys())

# No endpoint exposes a genuine server-side incremental filter — advertise nothing.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
