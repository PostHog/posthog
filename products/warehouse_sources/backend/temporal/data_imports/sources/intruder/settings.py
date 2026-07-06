from dataclasses import dataclass, field


@dataclass
class IntruderEndpointConfig:
    name: str
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable, creation-time datetime field used for datetime partitioning. Never a field that can
    # change over time (e.g. a "last seen"/"updated" column), which would rewrite partitions on
    # every sync. `None` means the endpoint has no such field, so the table is left unpartitioned.
    partition_key: str | None = None
    should_sync_default: bool = True
    # Fan out over every issue, calling `/issues/{issue_id}/occurrences/` per issue. When True,
    # `path` is a template with an `{issue_id}` placeholder and each row is tagged with its parent
    # `issue_id` so the composite primary key stays unique across the whole table.
    fan_out_over_issues: bool = False


# Intruder's REST API is full-refresh only: no list endpoint exposes a documented, verifiable
# server-side "created/updated after" cursor we can persist between runs, so every endpoint
# re-reads its full collection each sync (merge dedupes on the primary key). See source.py.
INTRUDER_ENDPOINTS: dict[str, IntruderEndpointConfig] = {
    "targets": IntruderEndpointConfig(name="targets", path="/targets/"),
    "scans": IntruderEndpointConfig(name="scans", path="/scans/", partition_key="created_at"),
    "scan_schedules": IntruderEndpointConfig(name="scan_schedules", path="/scans/schedules/"),
    "issues": IntruderEndpointConfig(name="issues", path="/issues/"),
    "occurrences": IntruderEndpointConfig(
        name="occurrences",
        path="/issues/{issue_id}/occurrences/",
        primary_keys=["issue_id", "id"],
        partition_key="first_seen_at",
        fan_out_over_issues=True,
    ),
    "fixed_occurrences": IntruderEndpointConfig(
        name="fixed_occurrences",
        path="/occurrences/fixed/",
        partition_key="first_seen_at",
    ),
    # Tags are returned as bare `{name}` objects with no numeric id, so `name` is the primary key.
    "tags": IntruderEndpointConfig(name="tags", path="/tags/", primary_keys=["name"]),
}

ENDPOINTS = tuple(INTRUDER_ENDPOINTS.keys())
