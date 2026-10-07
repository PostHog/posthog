from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField

# Loops caps `perPage` at 50 (allowed range 10-50, default 20) on cursor-paginated
# list endpoints.
PAGE_SIZE = 50


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
    # Set for per-object endpoints fetched once per row of a parent list endpoint.
    fanout: Optional[DependentEndpointConfig] = None
    # Unused by Loops' full-refresh endpoints; kept so the config satisfies FanoutEndpointLike.
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None
    page_size: int = PAGE_SIZE


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
    # The metrics bodies carry no id, so the parent's id is injected as the primary key.
    "campaign_metrics": LoopsEndpointConfig(
        name="campaign_metrics",
        path="/v1/campaigns/{campaignId}/metrics",
        primary_key="campaignId",
        paginated=False,
        fanout=DependentEndpointConfig(
            parent_name="campaigns",
            resolve_param="campaignId",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "campaignId"},
            parent_params={"perPage": PAGE_SIZE},
            # Loops answers 400 for a campaign that has not been sent yet or has no email
            # message, and 404 for one deleted after the parent listing. Neither has metrics.
            child_response_actions=[
                {"status_code": 400, "action": "ignore"},
                {"status_code": 404, "action": "ignore"},
            ],
        ),
    ),
    "transactional_email_metrics": LoopsEndpointConfig(
        name="transactional_email_metrics",
        path="/v1/transactional-emails/{transactionalId}/metrics",
        primary_key="transactionalId",
        paginated=False,
        fanout=DependentEndpointConfig(
            parent_name="transactional_emails",
            resolve_param="transactionalId",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "transactionalId"},
            parent_params={"perPage": PAGE_SIZE},
            child_response_actions=[{"status_code": 404, "action": "ignore"}],
        ),
    ),
}

ENDPOINTS = tuple(LOOPS_ENDPOINTS.keys())

# Loops list endpoints accept only perPage/cursor — no server-side timestamp
# filters — so every endpoint is full refresh only.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
