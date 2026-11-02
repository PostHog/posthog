from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField

# Frill serves every resource as a GET list endpoint under https://api.frill.co/v1 with
# cursor pagination (`after` param, `limit` capped at 100). No list endpoint exposes a
# server-side updated-since/created-since filter, so every stream is full refresh only
# (see source.py / frill.py). `/comments` requires an `idea_idx` query param, so comments
# fan out over the ideas list (one comments sub-pagination per idea).


@dataclass
class FrillEndpointConfig:
    # Path under the API base (https://api.frill.co/v1).
    path: str
    # Extra query params sent on every list request for this endpoint.
    params: dict[str, str] = field(default_factory=dict)
    # Stable creation timestamp — safe to partition on because it never changes after a
    # record is created (unlike `updated_at`). Statuses and topics carry no timestamps.
    partition_key: Optional[str] = "created_at"
    primary_keys: list[str] = field(default_factory=lambda: ["idx"])


FRILL_ENDPOINTS: dict[str, FrillEndpointConfig] = {
    "announcement_categories": FrillEndpointConfig(path="/announcement-categories"),
    # Both published and unpublished announcements are returned when `is_published` is omitted.
    "announcements": FrillEndpointConfig(path="/announcements"),
    # `idea_idx` is a required param on GET /comments, so this endpoint fans out over ideas.
    # `included_types` widens the default ('comments') to also sync internal notes; the row's
    # `type` field distinguishes them. Frill `idx` values are type-prefixed tokens (e.g.
    # `comment_abc123`) but the docs don't explicitly state global uniqueness, so the injected
    # parent idea idx is part of the key.
    "comments": FrillEndpointConfig(
        path="/comments",
        params={"included_types": "comments,notes"},
        primary_keys=["_idea_idx", "idx"],
    ),
    "followers": FrillEndpointConfig(path="/followers", params={"include_attributes": "true"}),
    "ideas": FrillEndpointConfig(path="/ideas"),
    "statuses": FrillEndpointConfig(path="/statuses", partition_key=None),
    "topics": FrillEndpointConfig(path="/topics", partition_key=None),
    "votes": FrillEndpointConfig(path="/votes"),
}

ENDPOINTS = tuple(FRILL_ENDPOINTS.keys())

# No endpoint exposes a server-side updated-since filter, so no stream is incremental.
# Kept for parity with other sources and for the (empty) per-endpoint advertised options.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {name: [] for name in FRILL_ENDPOINTS}
