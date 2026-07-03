from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class GuruEndpointConfig:
    name: str
    path: str
    primary_key: str = "id"
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation-time field used for datetime partitioning. Never an
    # updated_at-style field, which would rewrite partitions on every sync.
    partition_key: Optional[str] = None
    # Static query params sent on the first request of a page chain.
    extra_params: dict[str, str] = field(default_factory=dict)


# Guru responses are bare JSON arrays paginated via a `Link: <url>; rel="next-page"`
# header with an opaque continuation token. Only the card search surface supports a
# server-side date filter (Guru Query Language `lastModified >= <ISO8601>`); the
# dimension tables (collections, groups, members) are full refresh per run.
GURU_ENDPOINTS: dict[str, GuruEndpointConfig] = {
    "cards": GuruEndpointConfig(
        name="cards",
        path="/search/query",
        partition_key="dateCreated",
        extra_params={"queryType": "cards", "maxResults": "50"},
        incremental_fields=[
            {
                "label": "lastModified",
                "type": IncrementalFieldType.DateTime,
                "field": "lastModified",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "collections": GuruEndpointConfig(
        name="collections",
        path="/collections",
    ),
    "groups": GuruEndpointConfig(
        name="groups",
        path="/groups",
    ),
    "members": GuruEndpointConfig(
        name="members",
        path="/members",
        # Member rows have no top-level id; the transport copies user.email to a
        # top-level `email` so it can serve as the primary key.
        primary_key="email",
    ),
}

ENDPOINTS = tuple(GURU_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in GURU_ENDPOINTS.items() if config.incremental_fields
}
