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


@dataclass(frozen=True)
class DocusignFanOutConfig:
    """A per-parent request made for each row of the endpoint's own listing."""

    # Path under the account base URL, with `{parent_id}` standing in for the listed parent's id.
    path: str
    parent_id_key: str
    # Column the parent id is copied into on every child row.
    parent_id_column: str
    data_key: str
    params: dict[str, str] = field(default_factory=dict)
    paginated: bool = False
    # PowerForm form data nests one recipient list per submitted envelope.
    flatten_envelope_recipients: bool = False
    # Statuses that mean only this one parent is unreadable, so the table skips it instead of failing.
    skip_statuses: tuple[int, ...] = ()


@dataclass(frozen=True)
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
    # Per-envelope sub-resource (`/envelopes/{envelopeId}/<this>`) that the envelope listing has
    # no `include` for. Each listed envelope costs one extra request against the account's hourly
    # API quota, so these endpoints should be synced incrementally.
    envelope_sub_resource: Optional[str] = None
    envelope_sub_resource_params: dict[str, str] = field(default_factory=dict)
    fan_out: Optional[DocusignFanOutConfig] = None
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
    "envelope_custom_fields": DocusignEndpointConfig(
        name="envelope_custom_fields",
        path="/envelopes",
        data_key="envelopes",
        # Text and list custom fields are separate collections, so the type is part of the key.
        primary_key=["envelopeId", "customFieldType", "fieldId"],
        params={"order_by": "status_changed", "order": "asc", "include": "custom_fields"},
        date_filter_param="from_date",
        incremental_fields=_DERIVED_INCREMENTAL_FIELDS,
        partition_key="envelopeCreatedDateTime",
        derived_from_envelopes="custom_fields",
        envelope_child_keys=("customFields",),
    ),
    "envelope_form_data": DocusignEndpointConfig(
        name="envelope_form_data",
        path="/envelopes",
        data_key="envelopes",
        primary_key=["envelopeId"],
        # DocuSign only releases form data to the sender (or a full admin), so received envelopes
        # would fail the per-envelope request.
        params={"order_by": "status_changed", "order": "asc", "user_filter": "sender"},
        date_filter_param="from_date",
        incremental_fields=_DERIVED_INCREMENTAL_FIELDS,
        partition_key="envelopeCreatedDateTime",
        envelope_sub_resource="form_data",
    ),
    "envelope_audit_events": DocusignEndpointConfig(
        name="envelope_audit_events",
        path="/envelopes",
        data_key="envelopes",
        # Audit events carry no id of their own. The log is append-only and returned oldest
        # first, so an event's position in its envelope's log is stable.
        primary_key=["envelopeId", "eventIndex"],
        params={"order_by": "status_changed", "order": "asc"},
        date_filter_param="from_date",
        incremental_fields=_DERIVED_INCREMENTAL_FIELDS,
        partition_key="envelopeCreatedDateTime",
        envelope_sub_resource="audit_events",
    ),
    "envelope_templates": DocusignEndpointConfig(
        name="envelope_templates",
        path="/envelopes",
        data_key="envelopes",
        primary_key=["envelopeId", "templateId"],
        params={"order_by": "status_changed", "order": "asc"},
        date_filter_param="from_date",
        incremental_fields=_DERIVED_INCREMENTAL_FIELDS,
        partition_key="envelopeCreatedDateTime",
        envelope_sub_resource="templates",
        # Without a filter DocuSign can also return templates that merely match the documents.
        envelope_sub_resource_params={"include": "applied"},
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
    "bulk_send_batches": DocusignEndpointConfig(
        name="bulk_send_batches",
        path="/bulk_send_batch",
        data_key="bulkBatchSummaries",
        primary_key=["batchId"],
        # Without `from_date` DocuSign returns one account-wide status report instead of the
        # batch list. Full refresh only: the sent/failed/queued counts keep changing after a
        # batch is submitted, and `from_date` filters on submission time.
        date_filter_param="from_date",
        partition_key="submittedDate",
    ),
    "bulk_send_batch_envelopes": DocusignEndpointConfig(
        name="bulk_send_batch_envelopes",
        path="/bulk_send_batch",
        data_key="bulkBatchSummaries",
        primary_key=["bulkSendBatchId", "envelopeId"],
        # Same batch listing as `bulk_send_batches`. Full refresh only: envelope statuses keep
        # changing after the batch is submitted, and the batch filter is on submission time.
        date_filter_param="from_date",
        partition_key="createdDateTime",
        fan_out=DocusignFanOutConfig(
            path="/bulk_send_batch/{parent_id}/envelopes",
            parent_id_key="batchId",
            parent_id_column="bulkSendBatchId",
            data_key="envelopes",
            params={"order_by": "created", "order": "asc"},
            paginated=True,
        ),
    ),
    "powerforms": DocusignEndpointConfig(
        name="powerforms",
        path="/powerforms",
        data_key="powerForms",
        primary_key=["powerFormId"],
        # No from_date: DocuSign then applies no date filter, and usage counters change anyway.
        params={"order_by": "created", "order": "asc"},
        partition_key="createdDateTime",
    ),
    "powerform_form_data": DocusignEndpointConfig(
        name="powerform_form_data",
        path="/powerforms",
        data_key="powerForms",
        primary_key=["powerFormId", "envelopeId", "recipientId"],
        params={"order_by": "created", "order": "asc"},
        fan_out=DocusignFanOutConfig(
            path="/powerforms/{parent_id}/form_data",
            parent_id_key="powerFormId",
            parent_id_column="powerFormId",
            data_key="envelopes",
            params={"data_layout": "Native"},
            flatten_envelope_recipients=True,
            # Only PowerForm administrators and the PowerForm's sender can read its form data, and
            # the listing also returns PowerForms the user can see but not download.
            skip_statuses=(403, 404),
        ),
    ),
    "billing_invoices": DocusignEndpointConfig(
        name="billing_invoices",
        path="/billing_invoices",
        data_key="billingInvoices",
        primary_key=["invoiceId"],
        # Without from_date DocuSign returns only the last 365 days. Full refresh only, because
        # an invoice's balance changes when it is paid.
        date_filter_param="from_date",
        supports_pagination=False,
    ),
}

ENDPOINTS = tuple(DOCUSIGN_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in DOCUSIGN_ENDPOINTS.items() if config.incremental_fields
}
