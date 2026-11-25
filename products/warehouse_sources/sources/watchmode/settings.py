from dataclasses import dataclass, field
from typing import Any, Optional

from products.warehouse_sources.sources.sdk import DependentEndpointConfig, IncrementalField, ResponseAction

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
    # True when the response is one object, synced as one row, instead of a list.
    single_object: bool = False
    # Set for per-title endpoints that page with limit/offset instead of returning every row at once.
    offset_page_size: Optional[int] = None
    # True for the release calendar, which is read in date windows instead of pages.
    date_windowed: bool = False
    params: dict[str, Any] = field(default_factory=dict)
    fanout: Optional[DependentEndpointConfig] = None
    # Read by the shared fan-out builder; no Watchmode endpoint syncs incrementally.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None
    page_size: int = WATCHMODE_PAGE_LIMIT


_TITLES_PARAMS: dict[str, Any] = {"sort_by": "release_date_asc"}

# A title removed between the listing and its per-title request drops out of the sync.
_MISSING_TITLE_IGNORE: list[ResponseAction] = [{"status_code": 404, "action": "ignore"}]


# Seasons and episodes exist only for series, so the other title types would cost a request each for nothing.
_SERIES_TITLE_TYPES = "tv_series,tv_miniseries"


def _title_fanout(include_title_id: bool = True, title_types: Optional[str] = None) -> DependentEndpointConfig:
    parent_params: dict[str, Any] = {**_TITLES_PARAMS, "limit": WATCHMODE_PAGE_LIMIT}
    if title_types is not None:
        parent_params["types"] = title_types
    return DependentEndpointConfig(
        parent_name="titles",
        resolve_param="title_id",
        resolve_field="id",
        include_from_parent=["id"] if include_title_id else [],
        parent_field_renames={"id": "title_id"} if include_title_id else {},
        parent_params=parent_params,
        child_response_actions=_MISSING_TITLE_IGNORE,
    )


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
        params=_TITLES_PARAMS,
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
    "title_sources": WatchmodeEndpointConfig(
        name="title_sources",
        path="/v1/title/{title_id}/sources/",
        # A title can be on one service in several regions, both to rent and to buy, and in
        # several video formats, so each of these fields is part of the row identity.
        primary_keys=("title_id", "source_id", "region", "type", "format"),
        fanout=_title_fanout(),
    ),
    "title_details": WatchmodeEndpointConfig(
        name="title_details",
        path="/v1/title/{title_id}/details/",
        primary_keys=("id",),
        single_object=True,
        fanout=_title_fanout(include_title_id=False),
    ),
    "title_cast_crew": WatchmodeEndpointConfig(
        name="title_cast_crew",
        path="/v1/title/{title_id}/cast-crew/",
        # A person can act and direct in the same title, or hold several crew jobs.
        primary_keys=("title_id", "person_id", "type", "role"),
        fanout=_title_fanout(),
    ),
    "title_seasons": WatchmodeEndpointConfig(
        name="title_seasons",
        path="/v1/title/{title_id}/seasons/",
        primary_keys=("title_id", "id"),
        fanout=_title_fanout(title_types=_SERIES_TITLE_TYPES),
    ),
    "title_episodes": WatchmodeEndpointConfig(
        name="title_episodes",
        path="/v1/title/{title_id}/episodes/",
        primary_keys=("title_id", "id"),
        # Documented maximum `limit` for the episodes endpoint.
        offset_page_size=500,
        fanout=_title_fanout(title_types=_SERIES_TITLE_TYPES),
    ),
    "title_release_dates": WatchmodeEndpointConfig(
        name="title_release_dates",
        path="/v1/title-release-dates/",
        # One row per title, country and release kind. A series has one streaming row per season, and a
        # title can come to several services in one country, so the season, service and date are part of
        # the row identity. Theatrical rows have no service and no season.
        primary_keys=("id", "region", "type", "release_date", "provider_id", "season"),
        date_windowed=True,
    ),
}

ENDPOINTS = tuple(WATCHMODE_ENDPOINTS.keys())

# No endpoint gets incremental sync: the catalog endpoints expose no server-side
# timestamp filter, and the /changes/ endpoints (which do take start_date/end_date)
# return bare title-id integers with no per-row timestamp to watermark on, and are
# restricted to paid plans — so every table ships as full refresh. The per-title tables
# have no filter either, so each sync makes one request per title.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
