from dataclasses import dataclass, field


@dataclass
class MondayEndpointConfig:
    name: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


# monday.com is GraphQL-only. List queries have no honest updated-since
# filtering (incremental would need the activity log, whose retention window is
# plan-dependent), so every stream is a full refresh. Items use cursor paging
# whose cursors expire after 60 minutes, so nothing is persisted across runs.
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
}

ENDPOINTS = tuple(MONDAY_ENDPOINTS.keys())
