from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class TrelloEndpointConfig:
    name: str
    # For ``member`` scope this is the full path under the base URL
    # (e.g. ``/members/me/boards``). For ``board`` scope it is the trailing
    # segment fetched per board (e.g. ``cards`` → ``/boards/{board_id}/cards``).
    path: str
    # ``member`` = single top-level list request; ``board`` = fan out across the
    # authenticated member's boards and query the resource per board.
    scope: Literal["member", "board"]
    primary_key: str = "id"
    # We synthesise ``created_at`` from each object's ObjectID, so every endpoint
    # can partition on a stable creation timestamp (see ``_id_to_created_at``).
    partition_key: Optional[str] = "created_at"
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None
    # Trello caps a single response at 1000 objects. Only ``actions`` exposes the
    # ``before``/``since`` cursors needed to page past that and filter server-side.
    page_size: int = 1000
    paginated: bool = False
    sort_mode: Literal["asc", "desc"] = "asc"


# Actions are the only Trello resource with a genuine server-side timestamp filter
# (``since``), so it's the only endpoint that supports incremental sync. Everything
# else is full refresh. ``date`` is the action's immutable creation time.
_ACTIONS_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "date",
        "type": IncrementalFieldType.DateTime,
        "field": "date",
        "field_type": IncrementalFieldType.DateTime,
    },
]


TRELLO_ENDPOINTS: dict[str, TrelloEndpointConfig] = {
    "boards": TrelloEndpointConfig(
        name="boards",
        path="/members/me/boards",
        scope="member",
    ),
    "organizations": TrelloEndpointConfig(
        name="organizations",
        path="/members/me/organizations",
        scope="member",
    ),
    "lists": TrelloEndpointConfig(
        name="lists",
        path="lists",
        scope="board",
    ),
    "cards": TrelloEndpointConfig(
        name="cards",
        path="cards",
        scope="board",
    ),
    "checklists": TrelloEndpointConfig(
        name="checklists",
        path="checklists",
        scope="board",
    ),
    "labels": TrelloEndpointConfig(
        name="labels",
        path="labels",
        scope="board",
    ),
    "members": TrelloEndpointConfig(
        name="members",
        path="members",
        scope="board",
    ),
    "actions": TrelloEndpointConfig(
        name="actions",
        path="actions",
        scope="board",
        paginated=True,
        # Trello returns actions newest-first and ignores requests to sort
        # ascending, so the cursor watermark must be tracked as a descending feed.
        sort_mode="desc",
        incremental_fields=_ACTIONS_INCREMENTAL_FIELDS,
        default_incremental_field="date",
    ),
}

ENDPOINTS = tuple(TRELLO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in TRELLO_ENDPOINTS.items()
}
