from dataclasses import dataclass, field


@dataclass
class PapersignEndpointConfig:
    name: str
    # Path appended to the API base (https://api.paperform.co/v1).
    path: str
    # Key inside the response `results` object holding the row array
    # (e.g. `{"results": {"documents": [...]}}`).
    results_key: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # A stable, lifetime-constant datetime field used as the datetime partition key, or `None`
    # when the resource carries no such field. Papersign documents expose `created_at_utc`
    # (fixed at creation); folders and spaces have no timestamp at all, so they aren't partitioned.
    # `updated_at_utc` is never used — it shifts on every edit and would rewrite partitions each sync.
    partition_key: str | None = None
    # Whether the list endpoint accepts `?sort=ASC|DESC` (only documents does). We request `ASC`
    # so offset pagination stays stable: rows created mid-sync append at the end (a larger
    # `created_at`), leaving already-paged offsets untouched.
    supports_sort: bool = False
    should_sync_default: bool = True


# Papersign (Paperform's e-signature product) exposes three readable list endpoints. Each returns
# `{"status": "ok", "results": {"<resource>": [...]}, "total": N, "has_more": bool, "limit": 20,
# "skip": 0}` and is paginated by limit/skip offset (see papersign.py).
#
# Every table is full refresh. Documents advertise `after_date`/`before_date` filters on
# `created_at`, but (1) their documented semantics are inverted relative to their names and we could
# not curl-verify them, and (2) documents mutate over their lifetime (a document walks
# draft -> in_progress -> completed / canceled / expired / rejected), so a creation-time incremental
# sync would only ever capture new documents and silently miss those status transitions. Folders and
# spaces expose no timestamp filter at all. This mirrors the sibling e-signature source DocuSeal.
PAPERSIGN_ENDPOINTS: dict[str, PapersignEndpointConfig] = {
    "documents": PapersignEndpointConfig(
        name="documents",
        path="/papersign/documents",
        results_key="documents",
        partition_key="created_at_utc",
        supports_sort=True,
    ),
    "folders": PapersignEndpointConfig(
        name="folders",
        path="/papersign/folders",
        results_key="folders",
    ),
    "spaces": PapersignEndpointConfig(
        name="spaces",
        path="/papersign/spaces",
        results_key="spaces",
    ),
}

ENDPOINTS = tuple(PAPERSIGN_ENDPOINTS.keys())
