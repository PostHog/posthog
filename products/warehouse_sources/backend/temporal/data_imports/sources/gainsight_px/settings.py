from dataclasses import dataclass, field
from typing import Literal

from products.warehouse_sources.backend.types import IncrementalField

# Gainsight PX runs regional deployments. An API key belongs to a single subscription that lives in
# one region, so the host is picked by the `region` form field rather than a user-supplied URL — the
# set is fixed, so there is no SSRF surface.
GAINSIGHT_PX_HOSTS: dict[str, str] = {
    "us": "https://api.aptrinsic.com/v1",
    "eu": "https://api-eu.aptrinsic.com/v1",
    "us2": "https://api-us2.aptrinsic.com/v1",
}

# Scroll endpoints (users/accounts) cap `pageSize` at 1000; the page-number endpoints cap it lower
# (articles/kcbot allow up to 500). We keep the request size healthy but under each documented cap.
SCROLL_PAGE_SIZE = 1000
PAGE_NUMBER_PAGE_SIZE = 500

PaginationMode = Literal["scroll", "page"]

# Date fields come back as epoch-millisecond integers. We convert them to real datetimes before
# yielding so partition columns type as timestamps in the warehouse — the partitioner's integer
# branch assumes epoch *seconds*, so raw millis would produce nonsense partitions. `releaseDate`
# on articles is an ISO string, so it is deliberately excluded.
EPOCH_MILLIS_FIELDS: frozenset[str] = frozenset(
    {
        "createDate",
        "lastModifiedDate",
        "lastSeenDate",
        "signUpDate",
        "firstVisitDate",
        "renewalDate",
        "createdDate",
        "modifiedDate",
    }
)


@dataclass
class GainsightPxEndpointConfig:
    name: str
    path: str
    # The list of records is wrapped under a named key that varies per endpoint (e.g. `users`,
    # `articleExternalViewList`); this is that key.
    data_key: str
    pagination: PaginationMode
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Must be a STABLE creation datetime (never `lastModifiedDate`/`lastSeenDate`) so partitions
    # don't rewrite every sync. `None` for resources the API returns without a creation timestamp.
    partition_key: str | None = None
    page_size: int = SCROLL_PAGE_SIZE
    # No Gainsight PX list endpoint exposes a server-side "updated since" filter, so every table is
    # full refresh — declared here for parity with other sources and future incremental work.
    incremental_fields: list[IncrementalField] = field(default_factory=list)


# The entity endpoints Airbyte/Fivetran also expose. All are full refresh: the scroll endpoints
# (users/accounts) accept only `filter`/`sort`/`scrollId`, and the page-number endpoints accept only
# `pageNumber`/`pageSize` — none document an "updated since" server-side filter.
GAINSIGHT_PX_ENDPOINTS: dict[str, GainsightPxEndpointConfig] = {
    "accounts": GainsightPxEndpointConfig(
        name="accounts",
        path="/accounts",
        data_key="accounts",
        pagination="scroll",
        partition_key="createDate",
    ),
    "users": GainsightPxEndpointConfig(
        name="users",
        path="/users",
        data_key="users",
        pagination="scroll",
        partition_key="createDate",
    ),
    "features": GainsightPxEndpointConfig(
        name="features",
        path="/feature",
        data_key="features",
        pagination="page",
        page_size=PAGE_NUMBER_PAGE_SIZE,
    ),
    "segments": GainsightPxEndpointConfig(
        name="segments",
        path="/segment",
        data_key="segments",
        pagination="page",
        page_size=PAGE_NUMBER_PAGE_SIZE,
    ),
    "engagements": GainsightPxEndpointConfig(
        name="engagements",
        path="/engagement",
        data_key="engagements",
        pagination="page",
        page_size=PAGE_NUMBER_PAGE_SIZE,
    ),
    "articles": GainsightPxEndpointConfig(
        name="articles",
        path="/articles",
        data_key="articleExternalViewList",
        pagination="page",
        partition_key="createdDate",
        page_size=PAGE_NUMBER_PAGE_SIZE,
    ),
    "kc_bots": GainsightPxEndpointConfig(
        name="kc_bots",
        path="/kcbot",
        data_key="kcList",
        pagination="page",
        partition_key="createdDate",
        page_size=PAGE_NUMBER_PAGE_SIZE,
    ),
}

ENDPOINTS = tuple(GAINSIGHT_PX_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in GAINSIGHT_PX_ENDPOINTS.items()
}
