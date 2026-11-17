from dataclasses import field
from typing import Literal

from products.warehouse_sources.sources.sdk import IncrementalField, IncrementalFieldType, frozen

API_VERSION = "v2"
API_HOST = "moneybird.com"
BASE_URL = f"https://{API_HOST}/api/{API_VERSION}"

# Moneybird caps `per_page` at 100.
PAGE_SIZE = 100
# The synchronization POST returns at most 100 records, whatever the number of ids sent.
SYNC_BATCH_SIZE = 100
REQUEST_TIMEOUT = (10, 120)

# How the endpoint lists its records.
# - "paged": `page`/`per_page` pagination.
# - "single": one unpaginated list.
# - "synchronization": `GET <path>/synchronization` lists every id with its version, and
#   `POST <path>/synchronization` returns the full records for up to 100 ids.
FetchMode = Literal["paged", "single", "synchronization"]


@frozen
class MoneybirdEndpoint:
    path: str
    fetch_mode: FetchMode = "paged"
    params: dict[str, str] = field(default_factory=dict)
    # The `filter` param of a full refresh. Most list endpoints default to `period:this_year`
    # when no filter is sent, so a filter without `period` is what returns every record.
    base_filter: str | None = None
    # Endpoints with an `updated_after` filter term support incremental syncs on `updated_at`.
    supports_updated_after: bool = False
    # A synchronization endpoint can need more than one filter to cover every record. The ids of
    # all of them are joined.
    sync_filters: tuple[str, ...] = ()
    partition_key: str | None = "created_at"


ENDPOINTS: dict[str, MoneybirdEndpoint] = {
    # `/contacts` has no update filter. `/contacts/filter` returns the same records and has one.
    "contacts": MoneybirdEndpoint(
        path="contacts/filter",
        params={"include_archived": "true"},
        supports_updated_after=True,
    ),
    "sales_invoices": MoneybirdEndpoint(
        path="sales_invoices",
        base_filter="state:all",
        supports_updated_after=True,
    ),
    "estimates": MoneybirdEndpoint(path="estimates", base_filter="state:all"),
    "external_sales_invoices": MoneybirdEndpoint(path="external_sales_invoices", base_filter="state:all"),
    # The state filter has no `all` value and keeps its `active` default when left out, so the
    # sync lists the active and the inactive ids and joins them.
    "recurring_sales_invoices": MoneybirdEndpoint(
        path="recurring_sales_invoices",
        fetch_mode="synchronization",
        sync_filters=(
            "state:active,include_subscriptions:true",
            "state:inactive,include_subscriptions:true",
        ),
    ),
    "purchase_invoices": MoneybirdEndpoint(
        path="documents/purchase_invoices",
        base_filter="state:all",
        supports_updated_after=True,
    ),
    "receipts": MoneybirdEndpoint(
        path="documents/receipts",
        base_filter="state:all",
        supports_updated_after=True,
    ),
    "general_journal_documents": MoneybirdEndpoint(
        path="documents/general_journal_documents",
        base_filter="state:all",
        supports_updated_after=True,
    ),
    "general_documents": MoneybirdEndpoint(
        path="documents/general_documents",
        base_filter="state:all",
        supports_updated_after=True,
    ),
    "financial_accounts": MoneybirdEndpoint(path="financial_accounts", fetch_mode="single"),
    # The list endpoint answers 400 when more than 100 mutations match, so only the
    # synchronization endpoints can read every mutation.
    "financial_mutations": MoneybirdEndpoint(
        path="financial_mutations",
        fetch_mode="synchronization",
        sync_filters=("state:all",),
    ),
    "ledger_accounts": MoneybirdEndpoint(path="ledger_accounts", fetch_mode="single"),
    "tax_rates": MoneybirdEndpoint(path="tax_rates"),
    # `active=false` also returns the deactivated products.
    "products": MoneybirdEndpoint(path="products", params={"active": "false"}),
    "projects": MoneybirdEndpoint(path="projects", base_filter="state:all", partition_key=None),
    "time_entries": MoneybirdEndpoint(
        path="time_entries",
        base_filter="state:all,include_nil_contacts:true,include_active:true",
    ),
    "subscription_templates": MoneybirdEndpoint(path="subscription_templates", partition_key=None),
    "users": MoneybirdEndpoint(
        path="users",
        fetch_mode="single",
        params={"include_inactive": "true", "include_accountants": "true"},
    ),
    "workflows": MoneybirdEndpoint(path="workflows", fetch_mode="single"),
    "custom_fields": MoneybirdEndpoint(path="custom_fields", fetch_mode="single", partition_key=None),
}

UPDATED_AT_FIELD: IncrementalField = {
    "label": "updated_at",
    "type": IncrementalFieldType.DateTime,
    "field": "updated_at",
    "field_type": IncrementalFieldType.DateTime,
}

# `version` is the Unix time of the last change. The synchronization list carries it for every
# id, so an incremental sync fetches only the records whose version moved.
VERSION_FIELD: IncrementalField = {
    "label": "version",
    "type": IncrementalFieldType.Integer,
    "field": "version",
    "field_type": IncrementalFieldType.Integer,
}

INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {
    name: [UPDATED_AT_FIELD] if endpoint.supports_updated_after else [VERSION_FIELD]
    for name, endpoint in ENDPOINTS.items()
    if endpoint.supports_updated_after or endpoint.fetch_mode == "synchronization"
}
