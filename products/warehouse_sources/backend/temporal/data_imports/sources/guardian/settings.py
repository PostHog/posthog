from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


@dataclass
class GuardianEndpointConfig:
    name: str
    path: str
    incremental_fields: list[IncrementalField]
    # Stable publication timestamp used both as the incremental cursor and the partition key.
    # `webPublicationDate` never changes once an article is published, so it's safe to partition on.
    partition_key: Optional[str] = None
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    should_sync_default: bool = True
    # Extra query params always sent for this endpoint (e.g. field/tag selectors for richer payloads).
    extra_params: dict[str, str] = field(default_factory=dict)
    # Only the /search endpoint honors from-date/order-by=oldest as a server-side forward cursor.
    supports_incremental: bool = False


# The Guardian Open Platform Content API (https://open-platform.theguardian.com/documentation/).
# `content` is the primary stream (news articles etc.); `tags`, `sections` and `editions` are the
# supporting reference catalogs that content rows reference by id.
GUARDIAN_ENDPOINTS: dict[str, GuardianEndpointConfig] = {
    "content": GuardianEndpointConfig(
        name="content",
        path="/search",
        partition_key="webPublicationDate",
        supports_incremental=True,
        # `show-fields=all` / `show-tags=all` pull the article body, byline, wordcount, associated
        # tags etc. that the API omits by default. `order-by=oldest` + `order-date=published` yields
        # ascending `webPublicationDate` order so the incremental watermark advances correctly.
        extra_params={
            "show-fields": "all",
            "show-tags": "all",
            "show-references": "all",
            "order-by": "oldest",
            "order-date": "published",
        },
        incremental_fields=[
            {
                "label": "webPublicationDate",
                "type": IncrementalFieldType.DateTime,
                "field": "webPublicationDate",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "tags": GuardianEndpointConfig(
        name="tags",
        path="/tags",
        incremental_fields=[],
    ),
    "sections": GuardianEndpointConfig(
        name="sections",
        path="/sections",
        incremental_fields=[],
    ),
    "editions": GuardianEndpointConfig(
        name="editions",
        path="/editions",
        incremental_fields=[],
    ),
}

ENDPOINTS = tuple(GUARDIAN_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in GUARDIAN_ENDPOINTS.items()
}
