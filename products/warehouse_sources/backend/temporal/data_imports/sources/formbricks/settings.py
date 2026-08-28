from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType


def _datetime_incremental_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.DateTime,
        "field": name,
        "field_type": IncrementalFieldType.DateTime,
    }


@dataclass
class FormbricksEndpointConfig:
    name: str
    # Full request path including the /api/v1 or /api/v2 prefix. v1 and v2 management APIs
    # coexist; v2 is the paginated surface, but several resources are only listable on v1.
    path: str
    # v2 management list endpoints paginate with limit/skip and wrap rows in {"data": [...],
    # "meta": {...}}; v1 list endpoints return the whole collection in one {"data": [...]}
    # response and document no pagination params.
    paginated: bool = False
    # Only endpoints that document sortBy/order (responses) get them. Sending them to paginated
    # endpoints whose docs are silent (contact_attribute_keys, webhooks) risks a non-retryable
    # 400 from a strict validator; those small reference tables can rely on limit/skip alone.
    supports_sort: bool = False
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None
    partition_key: Optional[str] = None
    # Formbricks ids are cuids, unique per resource collection.
    primary_keys: list[str] = field(default_factory=lambda: ["id"])


# Incremental sync is only declared on `responses`: the v2 endpoint documents a server-side
# startDate/filterDateField window plus sortBy/order, so the filter and an ascending sort can be
# applied on every page. The other resources are small reference tables where a full refresh is
# cheaper than trusting an unverified filter. Verified against the public API docs; we have no
# live credentials, so behavior that docs leave ambiguous is handled conservatively.
FORMBRICKS_ENDPOINTS: dict[str, FormbricksEndpointConfig] = {
    "surveys": FormbricksEndpointConfig(
        name="surveys",
        path="/api/v1/management/surveys",
    ),
    "responses": FormbricksEndpointConfig(
        name="responses",
        path="/api/v2/management/responses",
        paginated=True,
        supports_sort=True,
        incremental_fields=[
            _datetime_incremental_field("updatedAt"),
            _datetime_incremental_field("createdAt"),
        ],
        # Responses mutate after creation (partial responses finish later), so updatedAt is the
        # default cursor that catches edits as well as new rows.
        default_incremental_field="updatedAt",
        partition_key="createdAt",
    ),
    "contacts": FormbricksEndpointConfig(
        name="contacts",
        path="/api/v1/management/contacts",
    ),
    "contact_attributes": FormbricksEndpointConfig(
        name="contact_attributes",
        path="/api/v1/management/contact-attributes",
    ),
    "contact_attribute_keys": FormbricksEndpointConfig(
        name="contact_attribute_keys",
        path="/api/v2/management/contact-attribute-keys",
        paginated=True,
    ),
    "action_classes": FormbricksEndpointConfig(
        name="action_classes",
        path="/api/v1/management/action-classes",
    ),
    "webhooks": FormbricksEndpointConfig(
        name="webhooks",
        path="/api/v2/management/webhooks",
        paginated=True,
    ),
}

ENDPOINTS = tuple(FORMBRICKS_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in FORMBRICKS_ENDPOINTS.items()
}
