from dataclasses import dataclass, field
from typing import Optional


@dataclass
class JustSiftEndpointConfig:
    name: str
    path: str
    # Every Sift object exposes a stable unique identifier — `id` for people, `objectKey` for the
    # field-definition catalog. Both are org-unique, so a single key suffices per table.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Sift's list endpoints expose no server-side creation timestamp to partition by, so this stays
    # unset and every table is imported as a single partition.
    partition_key: Optional[str] = None


# Sift (JustSift) API list endpoints. People are only listable through the search endpoint
# (`/search/people` with an empty query returns the whole directory, paginated); there is no
# `GET /people` that returns everyone. All endpoints are full-refresh only: Sift exposes no
# server-side `updated_after`-style filter, so there is no genuine incremental cursor to advance.
JUSTSIFT_ENDPOINTS: dict[str, JustSiftEndpointConfig] = {
    "people": JustSiftEndpointConfig(name="people", path="/search/people"),
    # A field's `objectKey` is the stable identifier used throughout the API (person keys, sortBy,
    # filters), so it is the natural primary key for the field catalog.
    "fields": JustSiftEndpointConfig(name="fields", path="/fields", primary_keys=["objectKey"]),
}

ENDPOINTS = tuple(JUSTSIFT_ENDPOINTS.keys())

# Full refresh only — no endpoint advertises an incremental cursor.
INCREMENTAL_FIELDS: dict[str, list] = {}
