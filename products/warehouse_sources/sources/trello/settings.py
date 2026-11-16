from dataclasses import dataclass, field
from typing import Any, Literal, Optional

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType


@dataclass(frozen=False)
class TrelloEndpointConfig:
    name: str
    # For ``member`` scope this is the full path under the base URL
    # (e.g. ``/members/me/boards``). For ``board`` scope it is the trailing
    # segment fetched per board (e.g. ``cards`` → ``/boards/{board_id}/cards``).
    path: str
    # ``member`` = single top-level list request; ``board`` = fan out across the
    # authenticated member's boards and query the resource per board.
    scope: Literal["member", "board"]
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
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
    # Endpoints that document no ``limit`` param skip it.
    send_limit: bool = True
    params: dict[str, Any] = field(default_factory=dict)
    # Set for tables built from an array nested in each parent object (e.g. a checklist's
    # ``checkItems``), which flattens the nested rows without a request per parent object.
    data_selector: Optional[str] = None
    # Adds a ``board_id`` column for board-scoped rows that carry no board reference of their own.
    include_board_id: bool = False


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
    "custom_fields": TrelloEndpointConfig(
        name="custom_fields",
        path="customFields",
        scope="board",
        send_limit=False,
    ),
    # ``/cards/{id}/customFieldItems`` would cost one request per card; the board's cards
    # endpoint returns the same items inline with ``customFieldItems=true``.
    "custom_field_items": TrelloEndpointConfig(
        name="custom_field_items",
        path="cards",
        scope="board",
        params={"fields": "id", "customFieldItems": "true"},
        data_selector="[*].customFieldItems[*]",
    ),
    # ``/checklists/{id}/checkItems`` would cost one request per checklist; the board's
    # checklists endpoint returns the same items inline.
    "check_items": TrelloEndpointConfig(
        name="check_items",
        path="checklists",
        scope="board",
        params={"fields": "id", "checkItems": "all"},
        data_selector="[*].checkItems[*]",
    ),
    "board_memberships": TrelloEndpointConfig(
        name="board_memberships",
        path="memberships",
        scope="board",
        primary_keys=["board_id", "id"],
        send_limit=False,
        include_board_id=True,
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
