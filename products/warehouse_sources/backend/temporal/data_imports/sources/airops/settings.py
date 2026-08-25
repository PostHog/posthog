from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField


@dataclass
class AirOpsEndpointConfig:
    name: str
    # Partition on a STABLE creation timestamp so partitions don't rewrite on every sync. Apps expose
    # `created_at`; executions expose `createdAt`.
    partition_key: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # AirOps exposes no server-side timestamp filter on either list endpoint, and executions mutate
    # after creation (status transitions, feedback), so every endpoint is full refresh only.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    should_sync_default: bool = True


AIROPS_ENDPOINTS: dict[str, AirOpsEndpointConfig] = {
    "apps": AirOpsEndpointConfig(
        name="apps",
        partition_key="created_at",
    ),
    "executions": AirOpsEndpointConfig(
        name="executions",
        partition_key="createdAt",
        # Execution ids are scoped per app, so the app id is part of the composite key to keep two
        # apps' executions that share an id from colliding into one warehouse row.
        primary_keys=["airops_app_id", "id"],
    ),
}

ENDPOINTS = tuple(AIROPS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in AIROPS_ENDPOINTS.items()
}
