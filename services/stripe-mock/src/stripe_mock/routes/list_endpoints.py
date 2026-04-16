from fastapi import APIRouter, Query, Request

from stripe_mock.data.store import store
from stripe_mock.pagination import paginate_list

router = APIRouter()

RESOURCE_MAP = {
    "accounts": "accounts",
    "balance_transactions": "balance_transactions",
    "charges": "charges",
    "customers": "customers",
    "disputes": "disputes",
    "invoiceitems": "invoice_items",
    "invoices": "invoices",
    "payouts": "payouts",
    "prices": "prices",
    "products": "products",
    "refunds": "refunds",
    "subscriptions": "subscriptions",
    "credit_notes": "credit_notes",
}


@router.get("/v1/{resource}")
async def list_resource(
    request: Request,
    resource: str,
    limit: int = Query(default=100, ge=1, le=100),
    starting_after: str | None = Query(default=None),
):
    collection_name = RESOURCE_MAP.get(resource)
    if not collection_name:
        return {"error": {"message": f"Unknown resource: {resource}", "type": "invalid_request_error"}}

    items = store.get_collection(collection_name)

    params = request.query_params
    created_gt = params.get("created[gt]")
    created_lt = params.get("created[lt]")
    if created_gt:
        items = [i for i in items if i.get("created", 0) > int(created_gt)]
    if created_lt:
        items = [i for i in items if i.get("created", 0) < int(created_lt)]

    status_filter = params.get("status")
    if status_filter and status_filter != "all":
        items = [i for i in items if i.get("status") == status_filter]

    return paginate_list(items, f"/v1/{resource}", limit, starting_after)
