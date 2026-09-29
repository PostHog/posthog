from dataclasses import field

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.types import IncrementalField

BASE_URL = "https://my.sevdesk.de/api"
PAGE_SIZE = 100

AUTH_ERROR = "Your sevDesk API token is invalid or expired. Generate a new token in sevDesk and reconnect."
PERMISSION_ERROR = "Your sevDesk user cannot access this table. Check the user's permissions in sevDesk."


@frozen
class SevdeskEndpoint:
    path: str
    primary_keys: tuple[str, ...] = ("id",)
    partition_key: str = "create"
    params: dict[str, str] = field(default_factory=dict)


ENDPOINTS: dict[str, SevdeskEndpoint] = {
    "Invoice": SevdeskEndpoint(path="Invoice", params={"showAll": "true"}),
    "InvoicePos": SevdeskEndpoint(path="InvoicePos"),
    "Voucher": SevdeskEndpoint(path="Voucher"),
    "VoucherPos": SevdeskEndpoint(path="VoucherPos"),
    "Order": SevdeskEndpoint(path="Order"),
    "OrderPos": SevdeskEndpoint(path="OrderPos"),
    "CreditNote": SevdeskEndpoint(path="CreditNote"),
    "CreditNotePos": SevdeskEndpoint(path="CreditNotePos"),
    "Contact": SevdeskEndpoint(path="Contact"),
    "Part": SevdeskEndpoint(path="Part"),
    "CheckAccount": SevdeskEndpoint(path="CheckAccount"),
    "CheckAccountTransaction": SevdeskEndpoint(path="CheckAccountTransaction"),
}

# Document-date windows miss edits to older documents; update filters need account-level verification.
INCREMENTAL_FIELDS: dict[str, list[IncrementalField]] = {}
