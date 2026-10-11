from dataclasses import dataclass, field

from products.warehouse_sources.backend.types import IncrementalField

# FRED's earliest addressable real-time date. `/fred/releases/dates` otherwise defaults
# `realtime_start` to the first day of the current year, which would clip the calendar to
# whatever year the sync happens to run in.
FRED_EARLIEST_REALTIME_DATE = "1776-07-04"


@dataclass
class FredEndpointConfig:
    name: str
    path: str
    # FRED nests every collection under a key named after the resource; `seriess` is the
    # API's own (sic) spelling for the series list.
    data_key: str
    primary_keys: list[str]
    # Endpoints taking a `series_id`: fetched once per series in the source's series list.
    per_series: bool = False
    # Stamp the requested series id onto each row. Observations and the per-series lookups
    # return no series identifier of their own, so without it their rows can't be told
    # apart once several series land in the same table.
    stamp_series_id: bool = False
    # Only the collection endpoints accept limit/offset. The per-series lookups return
    # their whole (small) result in a single response.
    paginated: bool = False
    page_size: int = 1000
    # Static query params: ordering (stable page boundaries) and realtime window.
    params: dict[str, str] = field(default_factory=dict)


FRED_ENDPOINTS: dict[str, FredEndpointConfig] = {
    "series": FredEndpointConfig(
        name="series",
        path="/series",
        data_key="seriess",
        primary_keys=["id"],
        per_series=True,
    ),
    "observations": FredEndpointConfig(
        name="observations",
        path="/series/observations",
        data_key="observations",
        primary_keys=["series_id", "date"],
        per_series=True,
        stamp_series_id=True,
        paginated=True,
        # The observations endpoint allows (and defaults to) 100000 rows per response, so
        # all but the longest daily series come back in one request.
        page_size=100000,
        params={"sort_order": "asc"},
    ),
    "series_categories": FredEndpointConfig(
        name="series_categories",
        path="/series/categories",
        data_key="categories",
        primary_keys=["series_id", "id"],
        per_series=True,
        stamp_series_id=True,
    ),
    "series_tags": FredEndpointConfig(
        name="series_tags",
        path="/series/tags",
        data_key="tags",
        primary_keys=["series_id", "name"],
        per_series=True,
        stamp_series_id=True,
        params={"order_by": "name", "sort_order": "asc"},
    ),
    "series_releases": FredEndpointConfig(
        name="series_releases",
        path="/series/release",
        data_key="releases",
        primary_keys=["series_id", "id"],
        per_series=True,
        stamp_series_id=True,
    ),
    "releases": FredEndpointConfig(
        name="releases",
        path="/releases",
        data_key="releases",
        primary_keys=["id"],
        paginated=True,
        params={"order_by": "release_id", "sort_order": "asc"},
    ),
    "release_dates": FredEndpointConfig(
        name="release_dates",
        path="/releases/dates",
        data_key="release_dates",
        primary_keys=["release_id", "date"],
        paginated=True,
        params={
            "order_by": "release_id",
            "sort_order": "asc",
            "include_release_dates_with_no_data": "true",
            "realtime_start": FRED_EARLIEST_REALTIME_DATE,
        },
    ),
    "sources": FredEndpointConfig(
        name="sources",
        path="/sources",
        data_key="sources",
        primary_keys=["id"],
        paginated=True,
        params={"order_by": "source_id", "sort_order": "asc"},
    ),
    "tags": FredEndpointConfig(
        name="tags",
        path="/tags",
        data_key="tags",
        primary_keys=["name"],
        paginated=True,
        params={"order_by": "name", "sort_order": "asc"},
    ),
}

ENDPOINTS = tuple(FRED_ENDPOINTS.keys())

# Every table is full refresh. `/fred/series/observations` does take a server-side
# `observation_start` filter, but the pipeline hands a source one watermark shared by every
# configured series, and FRED restates published observations after the fact. Driving
# `observation_start` off that single watermark would skip the whole back history of a
# series added after the first sync, and miss revisions to points behind it. Full pulls are
# cheap here (one request covers up to 100000 observations), so correctness wins.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
