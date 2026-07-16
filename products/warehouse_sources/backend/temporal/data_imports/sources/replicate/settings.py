from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# How the endpoint wraps its rows:
# - "paginated": Replicate's cursor pagination — `{"results": [...], "next": url, "previous": url}`.
# - "list": a bare JSON array (e.g. /v1/hardware).
# - "object": a single JSON object materialized as one row (e.g. /v1/account).
ResponseShape = Literal["paginated", "list", "object"]


@dataclass
class ReplicateEndpointConfig:
    name: str
    path: str
    response_shape: ResponseShape = "paginated"
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Stable, immutable field to partition by. Never a mutable field like a status timestamp.
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # The server-side query param that filters by the incremental field, if the API exposes one.
    # Only predictions documents a genuine server filter (`created_after`); everything else is
    # cursor-only and therefore ships full-refresh.
    time_filter_param: Optional[str] = None
    # Replicate's list endpoints return most-recent-first and expose no ascending sort, so the rows
    # arrive descending by created_at. SourceResponse.sort_mode must match the real emission order.
    sort_mode: Literal["asc", "desc"] = "desc"
    should_sync_default: bool = True


REPLICATE_ENDPOINTS: dict[str, ReplicateEndpointConfig] = {
    # Historical prediction (inference run) records. The only endpoint with a server-side timestamp
    # filter (`created_after`), so the only one that syncs incrementally. Predictions are immutable
    # once terminal; input/output/logs of API-created predictions are purged ~1h after completion
    # (`data_removed=true`), so older rows typically carry metadata only.
    "predictions": ReplicateEndpointConfig(
        name="predictions",
        path="/predictions",
        partition_key="created_at",
        time_filter_param="created_after",
        incremental_fields=[
            {
                "label": "created_at",
                "type": IncrementalFieldType.DateTime,
                "field": "created_at",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    # Fine-tune / training jobs. No documented timestamp filter, so full refresh only — a
    # client-side cursor walk would cost the same as a full refresh every run.
    "trainings": ReplicateEndpointConfig(
        name="trainings",
        path="/trainings",
        partition_key="created_at",
    ),
    # Deployments owned by the account. Small set, no timestamp filter — full refresh. Deployments
    # have no `id`; they are uniquely identified by owner + name.
    "deployments": ReplicateEndpointConfig(
        name="deployments",
        path="/deployments",
        primary_keys=["owner", "name"],
    ),
    # The full public model catalog exposed by /v1/models (not just the account's own models). Large,
    # so off by default; opt in when the catalog is genuinely wanted. Full refresh, keyed on
    # owner + name.
    "models": ReplicateEndpointConfig(
        name="models",
        path="/models",
        primary_keys=["owner", "name"],
        should_sync_default=False,
    ),
    # Static lookup of hardware SKUs available for running models. Bare JSON array, no pagination.
    "hardware": ReplicateEndpointConfig(
        name="hardware",
        path="/hardware",
        response_shape="list",
        primary_keys=["sku"],
    ),
    # The authenticated account. Single object materialized as one row.
    "account": ReplicateEndpointConfig(
        name="account",
        path="/account",
        response_shape="object",
        primary_keys=["username"],
    ),
}

ENDPOINTS = tuple(REPLICATE_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in REPLICATE_ENDPOINTS.items()
}
