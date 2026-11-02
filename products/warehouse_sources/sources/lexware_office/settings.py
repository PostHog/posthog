from dataclasses import field

from posthog.dataclasses import frozen

from products.warehouse_sources.backend.temporal.data_imports.sources.common.rest_source.fanout import (
    DependentEndpointConfig,
)
from products.warehouse_sources.backend.types import IncrementalField

BASE_URL = "https://api.lexware.io/v1"
PAGE_SIZE = 250
SEARCH_WINDOW_LIMIT = 10_000
BOOKKEEPING_TYPES = "salesinvoice,salescreditnote,purchaseinvoice,purchasecreditnote"
PAYMENT_TYPES = f"{BOOKKEEPING_TYPES},invoice,downpaymentinvoice,creditnote"


@frozen
class LexwareOfficeEndpoint:
    name: str
    path: str
    primary_key: str = "id"
    partition_key: str | None = None
    params: dict[str, str | int] = field(default_factory=dict)
    page_size: int = PAGE_SIZE
    incremental_fields: list[IncrementalField] = field(default_factory=list)
    default_incremental_field: str | None = None
    fanout: DependentEndpointConfig | None = None


def document_endpoint(name: str, path: str, voucher_type: str) -> LexwareOfficeEndpoint:
    return LexwareOfficeEndpoint(
        name=name,
        path=f"{path}/{{voucher_id}}",
        partition_key="createdDate",
        fanout=DependentEndpointConfig(
            parent_name="voucherlist",
            resolve_param="voucher_id",
            resolve_field="id",
            include_from_parent=["createdDate"],
            parent_field_renames={"createdDate": "createdDate"},
            parent_params={
                "voucherType": voucher_type,
                "voucherStatus": "any",
                "size": PAGE_SIZE,
                "sort": "createdDate,ASC",
            },
        ),
    )


ENDPOINTS: dict[str, LexwareOfficeEndpoint] = {
    "contacts": LexwareOfficeEndpoint(name="contacts", path="contacts"),
    "articles": LexwareOfficeEndpoint(name="articles", path="articles"),
    "voucherlist": LexwareOfficeEndpoint(
        name="voucherlist",
        path="voucherlist",
        partition_key="createdDate",
        params={"voucherType": "any", "voucherStatus": "any", "sort": "createdDate,ASC"},
    ),
    "invoices": document_endpoint("invoices", "invoices", "invoice"),
    "credit_notes": document_endpoint("credit_notes", "credit-notes", "creditnote"),
    "quotations": document_endpoint("quotations", "quotations", "quotation"),
    "delivery_notes": document_endpoint("delivery_notes", "delivery-notes", "deliverynote"),
    "order_confirmations": document_endpoint("order_confirmations", "order-confirmations", "orderconfirmation"),
    "down_payment_invoices": document_endpoint("down_payment_invoices", "down-payment-invoices", "downpaymentinvoice"),
    "vouchers": document_endpoint("vouchers", "vouchers", BOOKKEEPING_TYPES),
    "payments": LexwareOfficeEndpoint(
        name="payments",
        path="payments/{voucher_id}",
        primary_key="voucher_id",
        partition_key="createdDate",
        fanout=DependentEndpointConfig(
            parent_name="voucherlist",
            resolve_param="voucher_id",
            resolve_field="id",
            include_from_parent=["id", "createdDate"],
            parent_field_renames={"id": "voucher_id", "createdDate": "createdDate"},
            parent_params={
                "voucherType": PAYMENT_TYPES,
                "voucherStatus": "open,paid,paidoff,voided,transferred,sepadebit",
                "size": PAGE_SIZE,
                "sort": "createdDate,ASC",
            },
            # Linked credit notes have no independent payment information.
            child_response_actions=[{"status_code": 406, "action": "ignore"}],
        ),
    ),
}
