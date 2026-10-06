from dataclasses import field

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

QUO_BASE_URL = "https://api.quo.com"

# Quo caps `maxResults` at 100 on calls, messages and conversations, and at 50 on contacts.
# The users endpoint declares no maximum in the OpenAPI spec, so it stays on the lower cap.
MAX_PAGE_SIZE = 100
SMALL_PAGE_SIZE = 50


@frozen
class QuoEndpointConfig:
    name: str
    path: str
    primary_key: str = "id"
    # None means the endpoint returns the full collection in one unpaginated response.
    page_size: int | None = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Incremental field name -> the server-side query param that filters on it.
    incremental_params: dict[str, str] = field(default_factory=dict)
    # Stable creation-time field used for datetime partitioning, never an updated_at-style
    # field, which would rewrite partitions on every sync.
    partition_key: str | None = None
    # Quo requires `phoneNumberId` and `participants` on every calls/messages request, so those
    # endpoints fan out over the conversations list, which carries both per row.
    fan_out_over_conversations: bool = False
    # /v1/calls serves one-to-one conversations only (`participants` caps at one number);
    # /v1/messages accepts the full participants array of a group conversation.
    supports_group_conversations: bool = True


QUO_ENDPOINTS: dict[str, QuoEndpointConfig] = {
    "phone_numbers": QuoEndpointConfig(
        name="phone_numbers",
        path="/v1/phone-numbers",
        partition_key="createdAt",
    ),
    "users": QuoEndpointConfig(
        name="users",
        path="/v1/users",
        page_size=SMALL_PAGE_SIZE,
        partition_key="createdAt",
    ),
    "contacts": QuoEndpointConfig(
        name="contacts",
        path="/v1/contacts",
        page_size=SMALL_PAGE_SIZE,
        partition_key="createdAt",
    ),
    "contact_custom_fields": QuoEndpointConfig(
        name="contact_custom_fields",
        path="/v1/contact-custom-fields",
        primary_key="key",
    ),
    "conversations": QuoEndpointConfig(
        name="conversations",
        path="/v1/conversations",
        page_size=MAX_PAGE_SIZE,
        incremental_fields=[incremental_field("createdAt"), incremental_field("updatedAt")],
        incremental_params={"createdAt": "createdAfter", "updatedAt": "updatedAfter"},
        partition_key="createdAt",
    ),
    "calls": QuoEndpointConfig(
        name="calls",
        path="/v1/calls",
        page_size=MAX_PAGE_SIZE,
        incremental_fields=[incremental_field("createdAt")],
        incremental_params={"createdAt": "createdAfter"},
        partition_key="createdAt",
        fan_out_over_conversations=True,
        supports_group_conversations=False,
    ),
    "messages": QuoEndpointConfig(
        name="messages",
        path="/v1/messages",
        page_size=MAX_PAGE_SIZE,
        incremental_fields=[incremental_field("createdAt")],
        incremental_params={"createdAt": "createdAfter"},
        partition_key="createdAt",
        fan_out_over_conversations=True,
    ),
}

ENDPOINTS = tuple(QUO_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in QUO_ENDPOINTS.items() if config.incremental_fields
}
