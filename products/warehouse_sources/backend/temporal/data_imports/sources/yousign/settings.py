from dataclasses import dataclass, field
from typing import Any, Optional

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import incremental_field
from products.warehouse_sources.backend.types import IncrementalField

PRODUCTION_BASE_URL = "https://api.yousign.app/v3"
SANDBOX_BASE_URL = "https://api-sandbox.yousign.app/v3"

# Cursor-paginated list endpoints cap `limit` at 100 (workspaces defaults to 10, so we always
# pass the cap explicitly).
DEFAULT_PAGE_SIZE = 100

# The signature requests list defaults to `source[eq]=public_api`, silently hiding requests
# created from the Yousign app or other integrations. Override with every documented source so
# the warehouse sees the whole account; a value Yousign adds later would be missed until this
# list is updated.
SIGNATURE_REQUEST_SOURCES = (
    "app,public_api,hubspot_integration,connector_salesforce_api,connector_google_api,connector_zapier_api"
)

# Server-side date filters on the signature requests list (`<field>[after]=yyyy-mm-dd`). These
# are the only timestamp filters the v3 API exposes; every other list endpoint is full refresh.
SIGNATURE_REQUEST_INCREMENTAL_FIELDS: list[IncrementalField] = [
    incremental_field("created_at"),
    incremental_field("activated_at"),
    incremental_field("completed_at"),
]


@dataclass
class YousignEndpointConfig:
    name: str
    path: str
    # jsonpath into the response body: "data" for cursor-paginated wrappers, "$" for the bare
    # arrays the per-signature-request child endpoints return.
    data_selector: str
    primary_key: str | list[str]
    # Cursor pagination (`after` param, `meta.next_cursor` in the body). Child endpoints return
    # everything in one response.
    paginated: bool = True
    page_size: int = DEFAULT_PAGE_SIZE
    # Stable creation-time field for datetime partitioning; never an updated-style field.
    partition_key: Optional[str] = None
    params: dict[str, Any] = field(default_factory=dict)
    fanout: Optional[DependentEndpointConfig] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: Optional[str] = None
    supports_webhooks: bool = False
    description: Optional[str] = None


YOUSIGN_ENDPOINTS: dict[str, YousignEndpointConfig] = {
    "signature_requests": YousignEndpointConfig(
        name="signature_requests",
        path="/signature_requests",
        data_selector="data",
        primary_key="id",
        partition_key="created_at",
        params={"source[in]": SIGNATURE_REQUEST_SOURCES},
        incremental_fields=SIGNATURE_REQUEST_INCREMENTAL_FIELDS,
        default_incremental_field="created_at",
        supports_webhooks=True,
        description=(
            "One row per signature request, with embedded signer, approver, and document ids and their statuses."
        ),
    ),
    "signers": YousignEndpointConfig(
        name="signers",
        path="/signature_requests/{signatureRequestId}/signers",
        data_selector="$",
        # Signer ids are UUIDs, but the docs don't state global uniqueness — the parent id keeps
        # the key unique across the aggregated table.
        primary_key=["signature_request_id", "id"],
        paginated=False,
        fanout=DependentEndpointConfig(
            parent_name="signature_requests",
            resolve_param="signatureRequestId",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "signature_request_id"},
            parent_params={"source[in]": SIGNATURE_REQUEST_SOURCES},
        ),
        description="Signer details for every signature request, one row per signer.",
    ),
    "documents": YousignEndpointConfig(
        name="documents",
        path="/signature_requests/{signatureRequestId}/documents",
        data_selector="$",
        primary_key=["signature_request_id", "id"],
        paginated=False,
        partition_key="created_at",
        fanout=DependentEndpointConfig(
            parent_name="signature_requests",
            resolve_param="signatureRequestId",
            resolve_field="id",
            include_from_parent=["id"],
            parent_field_renames={"id": "signature_request_id"},
            parent_params={"source[in]": SIGNATURE_REQUEST_SOURCES},
        ),
        description="Document metadata for every signature request, one row per document.",
    ),
    "contacts": YousignEndpointConfig(
        name="contacts",
        path="/contacts",
        data_selector="data",
        primary_key="id",
        description="Contacts saved in the organization's contact book.",
    ),
    "users": YousignEndpointConfig(
        name="users",
        path="/users",
        data_selector="data",
        primary_key="id",
        partition_key="created_at",
        description="Members of the Yousign organization.",
    ),
    "workspaces": YousignEndpointConfig(
        name="workspaces",
        path="/workspaces",
        data_selector="data",
        primary_key="id",
        partition_key="created_at",
        description="Workspaces in the Yousign organization.",
    ),
    "labels": YousignEndpointConfig(
        name="labels",
        path="/labels",
        data_selector="data",
        primary_key="id",
        partition_key="created_at",
        description="Labels used to organize signature requests.",
    ),
}

ENDPOINTS = tuple(YOUSIGN_ENDPOINTS)

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in YOUSIGN_ENDPOINTS.items()
}

ENDPOINT_DESCRIPTIONS: dict[str, str] = {
    name: config.description for name, config in YOUSIGN_ENDPOINTS.items() if config.description
}

# Maps our schema name to the object type prefix of Yousign webhook event names
# (`signature_request.done` -> `signature_request`), used to route incoming webhooks to tables.
RESOURCE_TO_WEBHOOK_OBJECT_TYPE: dict[str, str] = {
    "signature_requests": "signature_request",
}

# Lifecycle events that change a signature request's state. Reminder events are excluded — they
# carry the same object without a state change and would only add delivery volume.
WEBHOOK_EVENTS: list[str] = [
    "signature_request.activated",
    "signature_request.approved",
    "signature_request.canceled",
    "signature_request.declined",
    "signature_request.deleted",
    "signature_request.done",
    "signature_request.expired",
    "signature_request.permanently_deleted",
    "signature_request.reactivated",
    "signature_request.rejected",
    "signature_request.paused",
    "signature_request.resumed",
]


def all_webhook_events() -> list[str]:
    return list(WEBHOOK_EVENTS)
