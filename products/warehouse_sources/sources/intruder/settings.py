from dataclasses import dataclass, field
from typing import Any

from products.warehouse_sources.sources.sdk import IncrementalField


@dataclass(frozen=True)
class IntruderFanOut:
    # Parent endpoint to iterate. The child `path` holds a `{parent_id_key}` placeholder, and each row
    # is tagged with that key so the composite primary key stays unique across the whole table.
    parent: str
    parent_id_key: str


@dataclass(frozen=True)
class IntruderEndpointConfig:
    name: str
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable, creation-time datetime field used for datetime partitioning. Never a field that can
    # change over time (e.g. a "last seen"/"updated" column), which would rewrite partitions on
    # every sync. `None` means the endpoint has no such field, so the table is left unpartitioned.
    partition_key: str | None = None
    should_sync_default: bool = True
    fan_out: IntruderFanOut | None = None
    params: dict[str, Any] = field(default_factory=dict)


_ISSUES_FAN_OUT = IntruderFanOut(parent="issues", parent_id_key="issue_id")

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
        fan_out=_ISSUES_FAN_OUT,
    ),
    # Target ids are only unique within an issue's list, and the rows carry no timestamp to partition on.
    "issue_targets": IntruderEndpointConfig(
        name="issue_targets",
        path="/issues/{issue_id}/targets/",
        primary_keys=["issue_id", "id"],
        fan_out=_ISSUES_FAN_OUT,
    ),
    "fixed_occurrences": IntruderEndpointConfig(
        name="fixed_occurrences",
        path="/occurrences/fixed/",
        partition_key="first_seen_at",
    ),
    # Tags are returned as bare `{name}` objects with no numeric id, so `name` is the primary key.
    "tags": IntruderEndpointConfig(name="tags", path="/tags/", primary_keys=["name"]),
    "attack_surface_services": IntruderEndpointConfig(
        name="attack_surface_services",
        path="/attack-surface/services/",
        partition_key="first_observed_at",
    ),
    # AI pentests are a separate Intruder product, so these tables are off by default.
    "ai_pentests": IntruderEndpointConfig(
        name="ai_pentests",
        path="/ai-pentests/",
        partition_key="created_at",
        should_sync_default=False,
    ),
    "ai_pentest_findings": IntruderEndpointConfig(
        name="ai_pentest_findings",
        path="/ai-pentests/{ai_pentest_id}/findings/",
        primary_keys=["ai_pentest_id", "id"],
        partition_key="first_seen_at",
        should_sync_default=False,
        fan_out=IntruderFanOut(parent="ai_pentests", parent_id_key="ai_pentest_id"),
        # The API returns only open findings unless told otherwise.
        params={"statuses": "open,fixed"},
    ),
}

ENDPOINTS = tuple(INTRUDER_ENDPOINTS.keys())

SHOULD_SYNC_DEFAULT: dict[str, bool] = {name: config.should_sync_default for name, config in INTRUDER_ENDPOINTS.items()}

# Every endpoint is full refresh: no list endpoint exposes a documented, verifiable server-side
# "created/updated after" cursor we can persist between runs, so nothing advertises incremental
# fields.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in INTRUDER_ENDPOINTS}
