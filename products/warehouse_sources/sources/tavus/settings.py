from dataclasses import dataclass, field
from typing import Any, Optional

from products.warehouse_sources.sources.sdk import DependentEndpointConfig

# Tavus list endpoints paginate with `page` (0-indexed) and `limit`; a large limit minimises round
# trips for the typically small tables.
PAGE_SIZE = 100


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
    params: dict[str, Any] = field(default_factory=dict)
    fanout: Optional[DependentEndpointConfig] = None
    # Read by the shared fan-out helper; every Tavus endpoint is full refresh.
    incremental_fields: list[Any] = field(default_factory=list)
    default_incremental_field: Optional[str] = None
    page_size: int = PAGE_SIZE


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
    # /faces and /pals are the current names of /replicas and /personas, with face_id and pal_id fields.
    # `verbose` adds face_type, which tells account faces from Tavus stock faces.
    "faces": TavusEndpointConfig(name="faces", path="/faces", primary_keys=["face_id"], params={"verbose": "true"}),
    "pals": TavusEndpointConfig(name="pals", path="/pals", primary_keys=["pal_id"]),
    "transcriptions": TavusEndpointConfig(
        name="transcriptions", path="/transcriptions", primary_keys=["transcription_id"]
    ),
    # Unpaginated per conversation. An interaction_id is unique only within its conversation.
    "canvas_interactions": TavusEndpointConfig(
        name="canvas_interactions",
        path="/conversations/{conversation_id}/canvas/interactions",
        primary_keys=["conversation_id", "interaction_id"],
        paginated=False,
        fanout=DependentEndpointConfig(
            parent_name="conversations",
            resolve_param="conversation_id",
            resolve_field="conversation_id",
            include_from_parent=["conversation_id"],
            parent_field_renames={"conversation_id": "conversation_id"},
        ),
    ),
}

ENDPOINTS = tuple(TAVUS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list] = {}
