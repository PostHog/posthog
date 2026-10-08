from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class TavusEndpointConfig:
    name: str
    path: str
    # Each Tavus resource exposes its own typed id field (video_id, replica_id, ...), so the
    # primary key is set per endpoint rather than shared.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # A stable (never-rewritten) creation timestamp to partition by. Left unset because the
    # Tavus list envelopes cannot be curl-verified for a guaranteed creation field.
    partition_key: Optional[str] = None
    # False for list endpoints that return every row in one response, with no page/limit params.
    paginated: bool = True


# Tavus v2 list endpoints. All are full-refresh only: the list endpoints expose no server-side
# created_after/updated_after filter, so there is no genuine incremental cursor to advance.
TAVUS_ENDPOINTS: dict[str, TavusEndpointConfig] = {
    "videos": TavusEndpointConfig(name="videos", path="/videos", primary_keys=["video_id"]),
    "replicas": TavusEndpointConfig(name="replicas", path="/replicas", primary_keys=["replica_id"]),
    "personas": TavusEndpointConfig(name="personas", path="/personas", primary_keys=["persona_id"]),
    "conversations": TavusEndpointConfig(name="conversations", path="/conversations", primary_keys=["conversation_id"]),
    "memory_stores": TavusEndpointConfig(
        name="memory_stores", path="/memory-stores", primary_keys=["memory_store_id"], paginated=False
    ),
}

ENDPOINTS = tuple(TAVUS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list] = {}
