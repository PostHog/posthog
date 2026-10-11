from dataclasses import dataclass
from typing import Literal

from products.warehouse_sources.backend.types import IncrementalField

BASE_URL = "https://api.tvmaze.com"

# TVmaze allows at least 20 requests per 10 seconds per IP; the transport-level
# retry already honors 429 + Retry-After, so no extra throttling layer is needed.
TVMazeEndpointKind = Literal["index", "updates"]


@dataclass
class TVMazeEndpointConfig:
    name: str
    path: str
    # "index" endpoints walk ?page=N (0-indexed) and terminate on the API's
    # documented 404 past the last page; "updates" endpoints return a single
    # {id: last_updated_unix_ts} map in one response.
    kind: TVMazeEndpointKind


ENDPOINT_CONFIGS: dict[str, TVMazeEndpointConfig] = {
    "shows": TVMazeEndpointConfig(
        name="shows",
        path="/shows",
        kind="index",
    ),
    "people": TVMazeEndpointConfig(
        name="people",
        path="/people",
        kind="index",
    ),
    "show_updates": TVMazeEndpointConfig(
        name="show_updates",
        path="/updates/shows",
        kind="updates",
    ),
    "person_updates": TVMazeEndpointConfig(
        name="person_updates",
        path="/updates/people",
        kind="updates",
    ),
}

ENDPOINTS = tuple(ENDPOINT_CONFIGS)

# TVmaze has no server-side timestamp filter on any endpoint (the /updates maps only
# accept coarse ?since=day|week|month windows, verified against the live API), so
# every table is full refresh only.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in ENDPOINTS}
