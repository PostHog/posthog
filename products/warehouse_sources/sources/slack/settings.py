from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.sources.sdk import IncrementalField, PartitionFormat, PartitionMode


@dataclass
class EndpointConfig:
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    partition_keys: Optional[list[str]] = None
    partition_mode: Optional[PartitionMode] = None
    partition_format: Optional[PartitionFormat] = None


ENDPOINTS: dict[str, EndpointConfig] = {
    "$channels": EndpointConfig(),
    "$users": EndpointConfig(),
}


def messages_endpoint_config() -> EndpointConfig:
    return EndpointConfig(
        primary_keys=["channel_id", "ts"],
        partition_keys=["timestamp"],
        partition_mode="datetime",
        partition_format="week",
    )
