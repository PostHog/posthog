from dataclasses import field

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.typings import SortMode
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@frozen
class MondayEndpointConfig:
    name: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    sort_mode: SortMode = "asc"
    partition_key: str | None = None


# monday.com is GraphQL-only. List queries have no honest updated-since
# filtering, so every stream except the board activity log is a full refresh.
# Items use cursor paging whose cursors expire after 60 minutes, so nothing is
# persisted across runs.
MONDAY_ENDPOINTS: dict[str, MondayEndpointConfig] = {
    "boards": MondayEndpointConfig(
        name="boards",
    ),
    "items": MondayEndpointConfig(
        name="items",
        # Item ids are globally unique, but keep the board linkage in the key
        # so re-parented items can't collide.
        primary_keys=["_board_id", "id"],
    ),
    "users": MondayEndpointConfig(
        name="users",
    ),
    "workspaces": MondayEndpointConfig(
        name="workspaces",
    ),
    "folders": MondayEndpointConfig(
        name="folders",
    ),
    # Column and group ids are only unique within their board.
    "board_columns": MondayEndpointConfig(
        name="board_columns",
        primary_keys=["_board_id", "id"],
    ),
    "board_groups": MondayEndpointConfig(
        name="board_groups",
        primary_keys=["_board_id", "id"],
    ),
    # `activity_logs(from:)` filters server-side, but each board returns its log
    # newest first. Retention of the log itself depends on the monday.com plan.
    "board_activity_logs": MondayEndpointConfig(
        name="board_activity_logs",
        primary_keys=["_board_id", "id"],
        incremental_fields=[
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        sort_mode="desc",
        partition_key="created_at",
    ),
}

ENDPOINTS = tuple(MONDAY_ENDPOINTS.keys())
