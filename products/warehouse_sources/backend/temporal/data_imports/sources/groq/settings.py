import dataclasses

from products.warehouse_sources.backend.types import IncrementalField

# Groq exposes an OpenAI-compatible REST API under a single global base URL. The queryable
# (list) endpoints are job/asset bookkeeping: batch jobs, uploaded files, and the model catalog.
# None of them offer a server-side timestamp filter (no `created_after` / `since`), so every table
# is full refresh only. Volumes are tiny (per-org job records), and batch artifacts expire upstream
# after ~30 days regardless, so a full refresh each run is cheap and correct.


@dataclasses.dataclass
class GroqEndpointConfig:
    name: str
    path: str
    # Unique across the whole table. Every Groq object carries a globally-unique `id`.
    primary_keys: list[str]
    # A stable creation timestamp (unix epoch seconds) used for datetime partitioning. Never a
    # mutable field. All three endpoints expose one, though the column name differs.
    partition_key: str
    # Whether this endpoint paginates via a body cursor. Only `batches` does; files and models are
    # returned as a single flat `data` array with no documented pagination.
    paginated: bool = False
    description: str | None = None
    should_sync_default: bool = True


GROQ_ENDPOINTS: dict[str, GroqEndpointConfig] = {
    "batches": GroqEndpointConfig(
        name="batches",
        path="/batches",
        primary_keys=["id"],
        partition_key="created_at",
        paginated=True,
        description="Batch inference jobs with status, request counts, input/output/error file IDs, and timestamps. Full refresh (batch inputs/outputs expire upstream after ~30 days).",
    ),
    "files": GroqEndpointConfig(
        name="files",
        path="/files",
        primary_keys=["id"],
        partition_key="created_at",
        description="Uploaded file metadata (filename, purpose, byte size, creation time). Full refresh.",
    ),
    "models": GroqEndpointConfig(
        name="models",
        path="/models",
        primary_keys=["id"],
        partition_key="created",
        description="Catalog of models available to your organization, including context window and ownership. Full refresh.",
    ),
}

ENDPOINTS = tuple(GROQ_ENDPOINTS.keys())

# Groq exposes no server-side timestamp filter on any list endpoint, so there is no reliable
# incremental cursor. Every table ships full refresh only.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in GROQ_ENDPOINTS}
