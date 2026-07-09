from dataclasses import dataclass, field
from typing import Literal, Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# How a list endpoint is walked:
# - "offset":   `limit`/`offset` query params over a bare JSON array (suppression endpoints).
# - "metadata": follow the absolute `_metadata.next` URL the API returns (marketing endpoints).
# - "single":   one request returns the whole list, no pagination params.
PaginationMode = Literal["offset", "metadata", "single"]


@dataclass
class SendGridEndpointConfig:
    name: str
    path: str
    primary_keys: list[str]
    pagination: PaginationMode
    # Key wrapping the array in the JSON response (e.g. {"result": [...]}). None when the
    # response body is the array itself (the suppression endpoints).
    data_key: Optional[str] = None
    # Stable creation field used for datetime partitioning. Never use a "modified" field here.
    partition_key: Optional[str] = None
    page_size: int = 500
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Server-side query param that filters by the incremental field (Unix epoch seconds).
    incremental_param: Optional[str] = None
    # Static query params always sent (e.g. templates' `generations`).
    extra_params: dict[str, str] = field(default_factory=dict)


def _epoch_field(name: str) -> IncrementalField:
    return {
        "label": name,
        "type": IncrementalFieldType.Integer,
        "field": name,
        "field_type": IncrementalFieldType.Integer,
    }


# SendGrid (v3) endpoint catalog. The suppression endpoints expose a genuine server-side
# `start_time` filter (Unix epoch seconds) over their immutable `created` field, so they sync
# incrementally. Marketing/asm metadata endpoints offer no timestamp filter and ship as full
# refresh. See api_inventory.md for the per-endpoint research notes.
SENDGRID_ENDPOINTS: dict[str, SendGridEndpointConfig] = {
    "bounces": SendGridEndpointConfig(
        name="bounces",
        path="/suppression/bounces",
        primary_keys=["email"],
        pagination="offset",
        partition_key="created",
        incremental_fields=[_epoch_field("created")],
        incremental_param="start_time",
    ),
    "blocks": SendGridEndpointConfig(
        name="blocks",
        path="/suppression/blocks",
        primary_keys=["email"],
        pagination="offset",
        partition_key="created",
        incremental_fields=[_epoch_field("created")],
        incremental_param="start_time",
    ),
    "invalid_emails": SendGridEndpointConfig(
        name="invalid_emails",
        path="/suppression/invalid_emails",
        primary_keys=["email"],
        pagination="offset",
        partition_key="created",
        incremental_fields=[_epoch_field("created")],
        incremental_param="start_time",
    ),
    "spam_reports": SendGridEndpointConfig(
        name="spam_reports",
        path="/suppression/spam_reports",
        primary_keys=["email"],
        pagination="offset",
        partition_key="created",
        incremental_fields=[_epoch_field("created")],
        incremental_param="start_time",
    ),
    "global_unsubscribes": SendGridEndpointConfig(
        name="global_unsubscribes",
        path="/suppression/unsubscribes",
        primary_keys=["email"],
        pagination="offset",
        partition_key="created",
        incremental_fields=[_epoch_field("created")],
        incremental_param="start_time",
    ),
    "unsubscribe_groups": SendGridEndpointConfig(
        name="unsubscribe_groups",
        path="/asm/groups",
        primary_keys=["id"],
        pagination="single",
    ),
    "marketing_lists": SendGridEndpointConfig(
        name="marketing_lists",
        path="/marketing/lists",
        primary_keys=["id"],
        pagination="metadata",
        data_key="result",
        page_size=100,
    ),
    "templates": SendGridEndpointConfig(
        name="templates",
        path="/templates",
        primary_keys=["id"],
        pagination="metadata",
        data_key="result",
        page_size=100,
        extra_params={"generations": "legacy,dynamic"},
    ),
}

ENDPOINTS = tuple(SENDGRID_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in SENDGRID_ENDPOINTS.items() if config.incremental_fields
}
