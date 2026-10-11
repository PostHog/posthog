from dataclasses import dataclass, field
from typing import Optional

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

# eSignature REST API version segment. DocuSign pins its API behind an explicit path version,
# and v2.1 is the current generally available one.
API_VERSION_PATH = "v2.1"

# DocuSign caps list pages at 100 rows across the account-scoped list endpoints.
PAGE_SIZE = 100

# `listStatusChanges` requires one of from_date / envelope_ids / transaction_ids, and silently
# limits results to the last two years when from_date is omitted. We always send an explicit
# from_date so the window is ours, not DocuSign's.
DEFAULT_LOOKBACK_DAYS = 730


@dataclass
class DocusignEndpointConfig:
    name: str
    # Path under `/restapi/v2.1/accounts/{accountId}`.
    path: str
    # Key the list of objects is nested under in the response body.
    data_key: str
    primary_key: list[str]
    # Query params sent on every page (page size and start_position are added by the transport).
    params: dict[str, str] = field(default_factory=dict)
    # Server-side filter name for the incremental watermark. Only set where DocuSign actually
    # filters on it; endpoints without one are full refresh.
    date_filter_param: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # Stable creation-time field used for datetime partitioning — never an updated-at style
    # field, which would rewrite partitions on every sync.
    partition_key: Optional[str] = None
    # Endpoints derived from the envelope listing: DocuSign returns the child collection inline
    # when `include` is set, which avoids the per-envelope GET that DocuSign rate-limits to one
    # request per envelope per 15 minutes.
    derived_from_envelopes: Optional[str] = None
    # Candidate keys the inline child collection arrives under on each envelope. DocuSign is not
    # consistent between the list and per-envelope shapes, so we accept either spelling.
    envelope_child_keys: tuple[str, ...] = ()
    # False for endpoints that return everything in one response and ignore `start_position` —
    # re-requesting with an advanced offset would replay the same rows forever.
    supports_pagination: bool = True


_ENVELOPE_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "statusChangedDateTime",
        "type": IncrementalFieldType.DateTime,
        "field": "statusChangedDateTime",
        "field_type": IncrementalFieldType.DateTime,
    },
]

_DERIVED_INCREMENTAL_FIELDS: list[IncrementalField] = [
    {
        "label": "envelopeStatusChangedDateTime",
        "type": IncrementalFieldType.DateTime,
        "field": "envelopeStatusChangedDateTime",
        "field_type": IncrementalFieldType.DateTime,
    },
]


DOCUSIGN_ENDPOINTS: dict[str, DocusignEndpointConfig] = {
    "envelopes": DocusignEndpointConfig(
        name="envelopes",
        path="/envelopes",
        data_key="envelopes",
        primary_key=["envelopeId"],
        # `status_changed` is the only ordering that lines up with what `from_date` filters on,
        # so the ascending watermark the pipeline checkpoints stays monotonic.
        params={"order_by": "status_changed", "order": "asc"},
        date_filter_param="from_date",
        incremental_fields=_ENVELOPE_INCREMENTAL_FIELDS,
        partition_key="createdDateTime",
    ),
    "envelope_recipients": DocusignEndpointConfig(
        name="envelope_recipients",
        path="/envelopes",
        data_key="envelopes",
        # Recipient ids are only unique within their envelope.
        primary_key=["envelopeId", "recipientId"],
        params={"order_by": "status_changed", "order": "asc", "include": "recipients"},
        date_filter_param="from_date",
        incremental_fields=_DERIVED_INCREMENTAL_FIELDS,
        partition_key="envelopeCreatedDateTime",
        derived_from_envelopes="recipients",
        envelope_child_keys=("recipients",),
    ),
    "envelope_documents": DocusignEndpointConfig(
        name="envelope_documents",
        path="/envelopes",
        data_key="envelopes",
        # Document ids restart at 1 in every envelope.
        primary_key=["envelopeId", "documentId"],
        params={"order_by": "status_changed", "order": "asc", "include": "documents"},
        date_filter_param="from_date",
        incremental_fields=_DERIVED_INCREMENTAL_FIELDS,
        partition_key="envelopeCreatedDateTime",
        derived_from_envelopes="documents",
        envelope_child_keys=("envelopeDocuments", "documents"),
    ),
    "templates": DocusignEndpointConfig(
        name="templates",
        path="/templates",
        data_key="envelopeTemplates",
        primary_key=["templateId"],
        params={"order_by": "modified", "order": "asc"},
        date_filter_param="from_date",
        incremental_fields=[
            {
                "label": "lastModified",
                "type": IncrementalFieldType.DateTime,
                "field": "lastModified",
                "field_type": IncrementalFieldType.DateTime,
            },
        ],
        partition_key="created",
    ),
    "users": DocusignEndpointConfig(
        name="users",
        path="/users",
        data_key="users",
        primary_key=["userId"],
        params={"additional_info": "true"},
        partition_key="createdDateTime",
    ),
    "folders": DocusignEndpointConfig(
        name="folders",
        path="/folders",
        data_key="folders",
        primary_key=["folderId"],
        supports_pagination=False,
    ),
}

ENDPOINTS = tuple(DOCUSIGN_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in DOCUSIGN_ENDPOINTS.items() if config.incremental_fields
}
