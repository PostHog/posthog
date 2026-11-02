from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class AssemblyAIEndpointConfig:
    name: str
    # List endpoint path (relative to the regional base URL).
    path: str
    # Field used to partition the warehouse table. Must be a stable creation timestamp,
    # never an updated_at-style field that rewrites partitions on every sync.
    partition_key: Optional[str] = None
    # Each list row is hydrated via GET {path}/{id} to fetch the full object (the list
    # endpoint only returns a summary). False would yield the list summary as-is.
    hydrate: bool = True
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    should_sync_default: bool = True


# AssemblyAI's only listable resource is Transcripts. The list endpoint (GET /v2/transcript)
# returns lightweight summaries (id/status/audio_url/created/completed); the full transcript —
# text, words, utterances, summary, sentiment, etc. — requires a per-id GET /v2/transcript/{id},
# so we hydrate each row.
#
# Full refresh only: the list endpoint exposes no server-side `created >= X` timestamp filter
# (only an exact `created_on=YYYY-MM-DD` day filter and non-monotonic UUID `after_id`/`before_id`
# cursors), so there is no watermark we can map a `db_incremental_field_last_value` onto. The API
# also only retains transcripts for the last 90 days. `created` is exposed as an incremental field
# option for the UI, but the schema advertises full refresh (see source.get_schemas).
ASSEMBLYAI_ENDPOINTS: dict[str, AssemblyAIEndpointConfig] = {
    "transcripts": AssemblyAIEndpointConfig(
        name="transcripts",
        path="/v2/transcript",
        partition_key="created",
        incremental_fields=[
            {
                "label": "created",
                "type": IncrementalFieldType.DateTime,
                "field": "created",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
}

ENDPOINTS = tuple(ASSEMBLYAI_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in ASSEMBLYAI_ENDPOINTS.items()
}
