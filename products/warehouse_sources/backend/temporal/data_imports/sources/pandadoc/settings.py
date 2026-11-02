from dataclasses import field
from typing import Literal, Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.typing import ResponseAction
from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# PandaDoc list pages cap at 100 items.
PAGE_SIZE = 100


@frozen
class PandaDocEndpointConfig:
    name: str
    # Relative to https://api.pandadoc.com/public, so it carries the endpoint's own /v1 or /v2 segment.
    path: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # Body key the list of rows lives under ("$" for a single-object response).
    data_key: str = "results"
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Maps an incremental cursor field to the server-side query param that filters on it
    # (e.g. date_modified -> modified_from). Only documents expose these filters.
    incremental_params: dict[str, str] = field(default_factory=dict)
    # Stable creation-time field used for datetime partitioning. Never an
    # updated_at-style field, which would rewrite partitions on every sync.
    partition_key: Optional[str] = None
    # "page": 1-based page number. "offset": limit/offset with a `count` total.
    # "none": the endpoint returns the full list in one response (contacts, members, per-document children).
    pagination: Literal["page", "offset", "none"] = "page"
    page_size_param: str = "count"
    page_size: int = PAGE_SIZE
    # Body flag some v2 list endpoints return to mark whether another page exists.
    has_more_path: Optional[str] = None
    default_incremental_field: Optional[str] = None
    fanout: Optional[DependentEndpointConfig] = None


# A document deleted between the parent listing and the child fetch 404s, and a document still
# being processed (document.uploaded) 409s. Both are skipped so the next sync picks them up.
_DOCUMENT_CHILD_IGNORE_404: list[ResponseAction] = [{"status_code": 404, "action": "ignore"}]
_DOCUMENT_CHILD_IGNORE_404_409: list[ResponseAction] = [
    {"status_code": 404, "action": "ignore"},
    {"status_code": 409, "action": "ignore"},
]


def _document_fanout(
    include_document_id: bool, child_response_actions: list[ResponseAction]
) -> DependentEndpointConfig:
    return DependentEndpointConfig(
        parent_name="documents",
        resolve_param="document_id",
        resolve_field="id",
        include_from_parent=["id"] if include_document_id else [],
        parent_field_renames={"id": "document_id"} if include_document_id else {},
        child_response_actions=child_response_actions,
    )


PANDADOC_ENDPOINTS: dict[str, PandaDocEndpointConfig] = {
    "documents": PandaDocEndpointConfig(
        name="documents",
        path="/v1/documents",
        partition_key="date_created",
        incremental_params={
            "date_modified": "modified_from",
            "date_created": "created_from",
        },
        incremental_fields=[
            {
                "label": "date_modified",
                "type": IncrementalFieldType.DateTime,
                "field": "date_modified",
                "field_type": IncrementalFieldType.DateTime,
            },
            {
                "label": "date_created",
                "type": IncrementalFieldType.DateTime,
                "field": "date_created",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
    ),
    "templates": PandaDocEndpointConfig(
        name="templates",
        path="/v1/templates",
    ),
    "forms": PandaDocEndpointConfig(
        name="forms",
        path="/v1/forms",
    ),
    "contacts": PandaDocEndpointConfig(
        name="contacts",
        path="/v1/contacts",
        pagination="none",
    ),
    "members": PandaDocEndpointConfig(
        name="members",
        path="/v1/members",
        primary_keys=["user_id"],
        pagination="none",
    ),
    "document_folders": PandaDocEndpointConfig(
        name="document_folders",
        path="/v1/documents/folders",
        primary_keys=["uuid"],
    ),
    "template_folders": PandaDocEndpointConfig(
        name="template_folders",
        path="/v1/templates/folders",
        primary_keys=["uuid"],
    ),
    # The search endpoint has no date filter, so the catalog is full refresh only.
    "product_catalog_items": PandaDocEndpointConfig(
        name="product_catalog_items",
        path="/v2/product-catalog/items/search",
        primary_keys=["uuid"],
        data_key="items",
        partition_key="date_created",
        page_size_param="per_page",
        has_more_path="has_more_items",
    ),
    # The document children are full refresh only. The audit trail and fields endpoints take no
    # date filter, and PandaDoc's `date_modified` does not move on content edits, so bounding the
    # parent listing by it would leave tokens, pricing and field values stale.
    "document_audit_trail": PandaDocEndpointConfig(
        name="document_audit_trail",
        path="/v2/documents/{document_id}/audit-trail",
        primary_keys=["document_id", "id"],
        partition_key="date_created",
        pagination="offset",
        page_size_param="limit",
        fanout=_document_fanout(include_document_id=True, child_response_actions=_DOCUMENT_CHILD_IGNORE_404),
    ),
    "document_fields": PandaDocEndpointConfig(
        name="document_fields",
        path="/v1/documents/{document_id}/fields",
        primary_keys=["document_id", "uuid"],
        data_key="fields",
        pagination="none",
        fanout=_document_fanout(include_document_id=True, child_response_actions=_DOCUMENT_CHILD_IGNORE_404_409),
    ),
    "document_details": PandaDocEndpointConfig(
        name="document_details",
        path="/v1/documents/{document_id}/details",
        data_key="$",
        partition_key="date_created",
        pagination="none",
        # The detail row already carries the document `id`.
        fanout=_document_fanout(include_document_id=False, child_response_actions=_DOCUMENT_CHILD_IGNORE_404_409),
    ),
}

ENDPOINTS = tuple(PANDADOC_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in PANDADOC_ENDPOINTS.items() if config.incremental_fields
}
