from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class BeamerEndpointConfig:
    name: str
    path: str
    primary_keys: list[str]
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation timestamp used for datetime partitioning. Never an update/last-seen field.
    partition_key: Optional[str] = None
    # Beamer caps page size per endpoint: 10 for posts/comments/reactions/requests/votes,
    # 100 for nps/users.
    max_results: int = 10
    # Only True where the endpoint exposes the server-side `dateFrom` filter on the `date` field.
    supports_incremental: bool = False
    should_sync_default: bool = True
    # Fan-out: when set, iterate the parent endpoint's rows and call `path` (with its `{parent_id}`
    # placeholder filled in) once per parent. `parent_key` is the column the parent id is injected
    # into on each child row so the composite primary key stays unique table-wide.
    parent: Optional[str] = None
    parent_key: Optional[str] = None


def _date_incremental_field() -> list[IncrementalField]:
    # Every incremental Beamer collection exposes a single `date` creation timestamp filtered by
    # the `dateFrom` query param.
    return [
        {
            "label": "date",
            "type": IncrementalFieldType.DateTime,
            "field": "date",
            "field_type": IncrementalFieldType.DateTime,
        }
    ]


BEAMER_ENDPOINTS: dict[str, BeamerEndpointConfig] = {
    "posts": BeamerEndpointConfig(
        name="posts",
        path="/posts",
        primary_keys=["id"],
        incremental_fields=_date_incremental_field(),
        partition_key="date",
        max_results=10,
        supports_incremental=True,
    ),
    "feature_requests": BeamerEndpointConfig(
        name="feature_requests",
        path="/requests",
        primary_keys=["id"],
        incremental_fields=_date_incremental_field(),
        partition_key="date",
        max_results=10,
        supports_incremental=True,
    ),
    "nps": BeamerEndpointConfig(
        name="nps",
        path="/nps",
        primary_keys=["id"],
        incremental_fields=_date_incremental_field(),
        partition_key="date",
        max_results=100,
        supports_incremental=True,
    ),
    # /users is Scale-plan only and exposes no `dateFrom` filter, so it's full refresh and off by
    # default to avoid 403-ing every non-Scale account's sync.
    "users": BeamerEndpointConfig(
        name="users",
        path="/users",
        primary_keys=["beamerId"],
        partition_key="firstSeen",
        max_results=100,
        supports_incremental=False,
        should_sync_default=False,
    ),
    # Fan-out children. Comments/reactions hang off posts; comments/votes hang off feature requests.
    # No server-side incremental on the fan-out (we'd still have to enumerate every parent), so these
    # are full refresh — merge dedupes the re-pulled rows on the composite primary key.
    "post_comments": BeamerEndpointConfig(
        name="post_comments",
        path="/posts/{parent_id}/comments",
        primary_keys=["post_id", "id"],
        partition_key="date",
        max_results=10,
        parent="posts",
        parent_key="post_id",
    ),
    "post_reactions": BeamerEndpointConfig(
        name="post_reactions",
        path="/posts/{parent_id}/reactions",
        primary_keys=["post_id", "id"],
        partition_key="date",
        max_results=10,
        parent="posts",
        parent_key="post_id",
        should_sync_default=False,
    ),
    "feature_request_comments": BeamerEndpointConfig(
        name="feature_request_comments",
        path="/requests/{parent_id}/comments",
        primary_keys=["feature_request_id", "id"],
        partition_key="date",
        max_results=10,
        parent="feature_requests",
        parent_key="feature_request_id",
    ),
    "feature_request_votes": BeamerEndpointConfig(
        name="feature_request_votes",
        path="/requests/{parent_id}/votes",
        primary_keys=["feature_request_id", "id"],
        partition_key="date",
        max_results=10,
        parent="feature_requests",
        parent_key="feature_request_id",
    ),
}

ENDPOINTS = tuple(BEAMER_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in BEAMER_ENDPOINTS.items()
}
