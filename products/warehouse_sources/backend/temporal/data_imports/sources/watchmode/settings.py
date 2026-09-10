from dataclasses import dataclass, field
from typing import Any, Optional

from products.warehouse_sources.backend.types import IncrementalField

WATCHMODE_BASE_URL = "https://api.watchmode.com"

# Documented maximum page size for paginated endpoints.
WATCHMODE_PAGE_LIMIT = 250


@dataclass(frozen=True)
class WatchmodeEndpointConfig:
    name: str
    path: str
    primary_keys: tuple[str, ...]
    # None means the endpoint returns a root-level JSON array with no wrapper object.
    data_selector: Optional[str] = None
    # True only for endpoints whose docs list page/limit params.
    paginated: bool = False
    params: dict[str, Any] = field(default_factory=dict)


WATCHMODE_ENDPOINTS: dict[str, WatchmodeEndpointConfig] = {
    "titles": WatchmodeEndpointConfig(
        name="titles",
        path="/v1/list-titles/",
        primary_keys=("id",),
        data_selector="titles",
        paginated=True,
        # The API's default sort (relevance_desc) can shift between page fetches; an
        # explicit stable sort avoids page-boundary skips/duplicates. New titles carry
        # recent release dates, so ascending release date keeps earlier pages stable.
        params={"sort_by": "release_date_asc"},
    ),
    "releases": WatchmodeEndpointConfig(
        name="releases",
        path="/v1/releases/",
        # The same title can land on several streaming services within the window, so
        # the title id alone is not unique per row.
        primary_keys=("id", "source_id"),
        data_selector="releases",
        paginated=True,
    ),
    "sources": WatchmodeEndpointConfig(
        name="sources",
        path="/v1/sources/",
        primary_keys=("id",),
    ),
    "regions": WatchmodeEndpointConfig(
        name="regions",
        path="/v1/regions/",
        # Region rows have no id field; the 2-letter country code is the row identity.
        primary_keys=("country",),
    ),
    "networks": WatchmodeEndpointConfig(
        name="networks",
        path="/v1/networks/",
        primary_keys=("id",),
    ),
    "genres": WatchmodeEndpointConfig(
        name="genres",
        path="/v1/genres/",
        primary_keys=("id",),
    ),
}

ENDPOINTS = tuple(WATCHMODE_ENDPOINTS.keys())

# No endpoint gets incremental sync: the catalog endpoints expose no server-side
# timestamp filter, and the /changes/ endpoints (which do take start_date/end_date)
# return bare title-id integers with no per-row timestamp to watermark on, and are
# restricted to paid plans — so every table ships as full refresh.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
