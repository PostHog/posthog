from fastapi import APIRouter, Query

from stripe_mock.data.store import store
from stripe_mock.pagination import paginate_search

router = APIRouter()

SEARCH_COLLECTIONS = {
    "customers": "customers",
    "subscriptions": "subscriptions",
    "invoices": "invoices",
}


@router.get("/v1/{resource}/search")
async def search_resource(
    resource: str,
    query: str = Query(default="created>0"),
    limit: int = Query(default=100, ge=1, le=100),
    page: str | None = Query(default=None),
):
    collection_name = SEARCH_COLLECTIONS.get(resource)
    if not collection_name:
        return {"error": {"message": f"Search not supported for: {resource}", "type": "invalid_request_error"}}

    items = store.get_collection(collection_name)
    return paginate_search(items, f"/v1/{resource}/search", limit, page)
