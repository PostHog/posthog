from fastapi import APIRouter, Query

from stripe_mock.data.store import store
from stripe_mock.pagination import paginate_list

router = APIRouter()


@router.get("/v1/customers/{customer_id}/balance_transactions")
async def list_customer_balance_transactions(
    customer_id: str,
    limit: int = Query(default=100, ge=1, le=100),
    starting_after: str | None = Query(default=None),
):
    items = store.filter_by("customer_balance_transactions", "customer", customer_id)
    return paginate_list(items, f"/v1/customers/{customer_id}/balance_transactions", limit, starting_after)


@router.get("/v1/customers/{customer_id}/payment_methods")
async def list_customer_payment_methods(
    customer_id: str,
    limit: int = Query(default=100, ge=1, le=100),
    starting_after: str | None = Query(default=None),
):
    items = store.filter_by("customer_payment_methods", "customer", customer_id)
    return paginate_list(items, f"/v1/customers/{customer_id}/payment_methods", limit, starting_after)


@router.get("/v1/invoices/{invoice_id}/lines")
async def list_invoice_lines(
    invoice_id: str,
    limit: int = Query(default=100, ge=1, le=100),
    starting_after: str | None = Query(default=None),
):
    invoice = store.get_by_id("invoices", invoice_id)
    if invoice and invoice.get("lines", {}).get("data"):
        items = invoice["lines"]["data"]
    else:
        items = [i for i in store.get_collection("invoice_line_items") if i.get("invoice") == invoice_id]
    return paginate_list(items, f"/v1/invoices/{invoice_id}/lines", limit, starting_after)
