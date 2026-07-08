from dataclasses import dataclass, field


@dataclass
class DocusealEndpointConfig:
    name: str
    path: str
    # `created_at` is stable for the row's lifetime, so it's a safe datetime partition key.
    # (DocuSeal objects also carry `updated_at`, but that shifts on every edit and would
    # rewrite partitions each sync, so we never partition on it.)
    partition_key: str = "created_at"
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True


# DocuSeal exposes three top-level list endpoints. Each is a flat `{"data": [...],
# "pagination": {...}}` response paginated by record id (see docuseal.py). The API has no
# server-side timestamp filter and objects mutate over their lifetime (a submission walks
# pending -> completed -> declined), so every table is full refresh — an append-only sync keyed
# on the monotonic id would only ever capture new records and silently miss those status updates.
DOCUSEAL_ENDPOINTS: dict[str, DocusealEndpointConfig] = {
    "templates": DocusealEndpointConfig(name="templates", path="/templates"),
    "submissions": DocusealEndpointConfig(name="submissions", path="/submissions"),
    "submitters": DocusealEndpointConfig(name="submitters", path="/submitters"),
}

ENDPOINTS = tuple(DOCUSEAL_ENDPOINTS.keys())
