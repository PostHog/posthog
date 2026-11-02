from dataclasses import field
from typing import Optional

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField, IncrementalFieldType

EASYBILL_BASE_URL = "https://api.easybill.de/rest/v1"

# Every list endpoint accepts the same limit/page params, capped at 1000. Requesting the maximum
# keeps request counts low under easybill's tight per-minute rate limits (10/min on PLUS, 60/min
# on BUSINESS).
PAGE_LIMIT = 1000


@frozen
class EasybillEndpointConfig:
    name: str
    path: str
    table_name: str
    primary_keys: list[str] = field(default_factory=lambda: ["id"])
    # A stable, creation-time field for datetime partitioning. None when the endpoint exposes no
    # field that's guaranteed not to change after the row is written.
    partition_key: Optional[str] = None
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    # The query param that filters this endpoint by date, if it reliably tracks record
    # modification (e.g. "edited_at"). None means full refresh: either there's no date filter, or
    # the only one available is a business date (a payment/creation date) that doesn't catch
    # updates to existing rows.
    incremental_param: Optional[str] = None


def _edited_at_field() -> list[IncrementalField]:
    return [
        {
            "label": "edited_at",
            "type": IncrementalFieldType.DateTime,
            "field": "edited_at",
            "field_type": IncrementalFieldType.DateTime,
        }
    ]


EASYBILL_ENDPOINTS: dict[str, EasybillEndpointConfig] = {
    # The money table: invoices, credit notes, offers, delivery notes and more, distinguished by
    # `type`. `edited_at` is a real last-modified timestamp, so this is the one endpoint that
    # syncs incrementally.
    "Documents": EasybillEndpointConfig(
        name="Documents",
        path="/documents",
        table_name="documents",
        partition_key="created_at",
        incremental_fields=_edited_at_field(),
        incremental_param="edited_at",
    ),
    "DocumentPayments": EasybillEndpointConfig(
        name="DocumentPayments",
        path="/document-payments",
        table_name="document_payments",
    ),
    # Received supplier invoices and credit notes. The list endpoint only filters by `created_at`,
    # so — like `/customers` — it stays full refresh: a `created_at` cursor would miss later edits
    # (status, payments, `is_paid`) that bump `updated_at` but not the creation date.
    "IncomingDocuments": EasybillEndpointConfig(
        name="IncomingDocuments",
        path="/incoming-documents",
        table_name="incoming_documents",
        partition_key="created_at",
    ),
    # `/customers` only filters by `created_at`, which would miss edits to existing customers, so
    # this stays full refresh rather than syncing on a lossy cursor.
    "Customers": EasybillEndpointConfig(
        name="Customers",
        path="/customers",
        table_name="customers",
        partition_key="created_at",
    ),
    "Positions": EasybillEndpointConfig(
        name="Positions",
        path="/positions",
        table_name="positions",
    ),
    "Projects": EasybillEndpointConfig(
        name="Projects",
        path="/projects",
        table_name="projects",
    ),
    "CustomerGroups": EasybillEndpointConfig(
        name="CustomerGroups",
        path="/customer-groups",
        table_name="customer_groups",
    ),
}

ENDPOINTS = tuple(EASYBILL_ENDPOINTS.keys())

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: config.incremental_fields for name, config in EASYBILL_ENDPOINTS.items()
}
