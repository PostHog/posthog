from dataclasses import dataclass, field
from enum import Enum

from products.warehouse_sources.backend.types import IncrementalField


class PaginationStyle(Enum):
    # Browse endpoint returns an opaque `cursor` token; absence of the token signals end of index.
    CURSOR = "cursor"
    # Search endpoints (synonyms/rules) and `GET /1/indexes` use 0-based `page` numbers.
    PAGE = "page"


@dataclass
class AlgoliaEndpointConfig:
    name: str
    # Path on the Algolia REST API. `{index}` is substituted with the configured index name.
    path: str
    method: str
    pagination: PaginationStyle
    # Key in the JSON response that holds the list of rows (`hits`, `items`).
    data_selector: str
    primary_keys: list[str] = field(default_factory=lambda: ["objectID"])
    # Whether the endpoint targets a specific index (so it needs the `index_name` field).
    requires_index: bool = True
    should_sync_default: bool = True
    # Rows requested per page (`hitsPerPage`). Algolia caps browse/search at 1000.
    page_size: int = 1000
    incremental_fields: list[IncrementalField] = field(default_factory=list)


# All Algolia endpoints below are full-refresh: the index browse endpoint and the
# synonyms/rules search endpoints expose no server-side "updated since" filter, so an
# incremental sync would still page the whole resource. The cursor (browse) and page
# (search/list) tokens make every endpoint resumable, so a heartbeat timeout picks back
# up where it left off rather than restarting.
ALGOLIA_ENDPOINTS: dict[str, AlgoliaEndpointConfig] = {
    "records": AlgoliaEndpointConfig(
        name="records",
        path="/1/indexes/{index}/browse",
        method="POST",
        pagination=PaginationStyle.CURSOR,
        data_selector="hits",
        primary_keys=["objectID"],
    ),
    "synonyms": AlgoliaEndpointConfig(
        name="synonyms",
        path="/1/indexes/{index}/synonyms/search",
        method="POST",
        pagination=PaginationStyle.PAGE,
        data_selector="hits",
        primary_keys=["objectID"],
        should_sync_default=False,
    ),
    "rules": AlgoliaEndpointConfig(
        name="rules",
        path="/1/indexes/{index}/rules/search",
        method="POST",
        pagination=PaginationStyle.PAGE,
        data_selector="hits",
        primary_keys=["objectID"],
        should_sync_default=False,
    ),
    "indices": AlgoliaEndpointConfig(
        name="indices",
        path="/1/indexes",
        method="GET",
        pagination=PaginationStyle.PAGE,
        data_selector="items",
        primary_keys=["name"],
        requires_index=False,
        should_sync_default=False,
    ),
}

ENDPOINTS = tuple(ALGOLIA_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in ALGOLIA_ENDPOINTS.items()
}
