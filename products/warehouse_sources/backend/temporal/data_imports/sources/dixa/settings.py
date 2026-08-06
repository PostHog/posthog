from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class DixaEndpointConfig:
    name: str
    path: str
    # Dixa has two API surfaces: the main API (dev.dixa.io/v1, cursor-paginated
    # dimension tables) and the Exports API (exports.dixa.io/v1, time-windowed
    # bulk arrays with strict per-minute rate limits).
    surface: Literal["main", "export"]
    primary_key: str = "id"
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation-time field used for datetime partitioning (Unix ms).
    partition_key: Optional[str] = None


DIXA_ENDPOINTS: dict[str, DixaEndpointConfig] = {
    "conversations": DixaEndpointConfig(
        name="conversations",
        path="/conversation_export",
        surface="export",
        partition_key="created_at",
        incremental_fields=[
            {
                "label": "updated_at",
                "type": IncrementalFieldType.DateTime,
                "field": "updated_at",
                "field_type": IncrementalFieldType.Integer,
            },
        ],
    ),
    "agents": DixaEndpointConfig(
        name="agents",
        path="/agents",
        surface="main",
    ),
    "endusers": DixaEndpointConfig(
        name="endusers",
        path="/endusers",
        surface="main",
    ),
    "queues": DixaEndpointConfig(
        name="queues",
        path="/queues",
        surface="main",
    ),
    "tags": DixaEndpointConfig(
        name="tags",
        path="/tags",
        surface="main",
    ),
}

ENDPOINTS = tuple(DIXA_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in DIXA_ENDPOINTS.items() if config.incremental_fields
}
