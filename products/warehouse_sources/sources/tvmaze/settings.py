from dataclasses import dataclass, field
from typing import Literal

from products.warehouse_sources.sources.sdk import DependentEndpointConfig, IncrementalField

BASE_URL = "https://api.tvmaze.com"

# TVmaze allows at least 20 requests per 10 seconds per IP; the transport-level
# retry already honors 429 + Retry-After, so no extra throttling layer is needed.
TVMazeEndpointKind = Literal["index", "updates", "fanout"]

# The show index returns a fixed 250 rows per page and takes no page-size param.
INDEX_PAGE_SIZE = 250

_SHOW_FANOUT = DependentEndpointConfig(
    parent_name="shows",
    resolve_param="show_id",
    resolve_field="id",
    include_from_parent=["id"],
    parent_field_renames={"id": "show_id"},
    # A show deleted between the index read and its child request returns 404.
    child_response_actions=[{"status_code": 404, "action": "ignore"}],
)


@dataclass(frozen=False)
class TVMazeEndpointConfig:
    name: str
    path: str
    # "index" endpoints walk ?page=N (0-indexed) and terminate on the API's
    # documented 404 past the last page; "updates" endpoints return a single
    # {id: last_updated_unix_ts} map in one response; "fanout" endpoints request
    # one unpaginated list per show from the show index.
    kind: TVMazeEndpointKind
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    fanout: DependentEndpointConfig | None = None
    page_size: int = INDEX_PAGE_SIZE
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None


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
    "seasons": TVMazeEndpointConfig(
        name="seasons",
        path="/shows/{show_id}/seasons",
        kind="fanout",
        primary_keys=["show_id", "id"],
        fanout=_SHOW_FANOUT,
    ),
    "episodes": TVMazeEndpointConfig(
        name="episodes",
        # specials=1 adds the special episodes, which the default list leaves out.
        path="/shows/{show_id}/episodes?specials=1",
        kind="fanout",
        primary_keys=["show_id", "id"],
        fanout=_SHOW_FANOUT,
    ),
    "cast": TVMazeEndpointConfig(
        name="cast",
        path="/shows/{show_id}/cast",
        kind="fanout",
        # Cast rows have no id of their own: one row is one person playing one character.
        primary_keys=["show_id", "person_id", "character_id"],
        fanout=_SHOW_FANOUT,
    ),
}

ENDPOINTS = tuple(ENDPOINT_CONFIGS)

# TVmaze has no server-side timestamp filter on any endpoint (the /updates maps only
# accept coarse ?since=day|week|month windows, verified against the live API), so
# every table is full refresh only.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in ENDPOINTS}
