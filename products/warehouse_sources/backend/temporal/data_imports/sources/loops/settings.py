from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField


@dataclass
class LoopsEndpointConfig:
    name: str
    # Path under https://app.loops.so/api (e.g. "/v1/campaigns").
    path: str
    primary_key: str = "id"
    # Stable created-date field to partition by, or None when the payload has no
    # creation timestamp (mailing lists, contact properties, components).
    partition_key: Optional[str] = None
    # Whether the endpoint uses Loops' cursor pagination and wraps rows as
    # {"pagination": {...}, "data": [...]}. Unpaginated endpoints return the
    # full collection as a bare JSON array.
    paginated: bool = True
    # Extra query params merged into every request for this endpoint.
    extra_params: dict[str, str] = field(default_factory=dict)


LOOPS_ENDPOINTS: dict[str, LoopsEndpointConfig] = {
    "campaigns": LoopsEndpointConfig(
        name="campaigns",
        path="/v1/campaigns",
        partition_key="createdAt",
    ),
    "campaign_groups": LoopsEndpointConfig(
        name="campaign_groups",
        path="/v1/campaign-groups",
        partition_key="createdAt",
    ),
    "mailing_lists": LoopsEndpointConfig(
        name="mailing_lists",
        path="/v1/lists",
        paginated=False,
    ),
    "audience_segments": LoopsEndpointConfig(
        name="audience_segments",
        path="/v1/audience-segments",
        partition_key="createdAt",
    ),
    "workflows": LoopsEndpointConfig(
        name="workflows",
        path="/v1/workflows",
        partition_key="createdAt",
    ),
    "transactional_emails": LoopsEndpointConfig(
        name="transactional_emails",
        path="/v1/transactional-emails",
        partition_key="createdAt",
    ),
    "transactional_groups": LoopsEndpointConfig(
        name="transactional_groups",
        path="/v1/transactional-groups",
        partition_key="createdAt",
    ),
    "contact_properties": LoopsEndpointConfig(
        name="contact_properties",
        path="/v1/contacts/properties",
        primary_key="key",
        paginated=False,
        extra_params={"list": "all"},
    ),
    "themes": LoopsEndpointConfig(
        name="themes",
        path="/v1/themes",
        partition_key="createdAt",
    ),
    "components": LoopsEndpointConfig(
        name="components",
        path="/v1/components",
    ),
}

ENDPOINTS = tuple(LOOPS_ENDPOINTS.keys())

# Loops list endpoints accept only perPage/cursor — no server-side timestamp
# filters — so every endpoint is full refresh only.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
