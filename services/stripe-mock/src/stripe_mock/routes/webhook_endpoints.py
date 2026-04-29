import uuid

from fastapi import APIRouter, Request

from stripe_mock.pagination import paginate_list

router = APIRouter()

_webhooks: list[dict] = []


@router.post("/v1/webhook_endpoints")
async def create_webhook(request: Request):
    body = await request.form()
    wh = {
        "id": f"we_{uuid.uuid4().hex[:24]}",
        "object": "webhook_endpoint",
        "url": body.get("url", ""),
        "enabled_events": list(body.getlist("enabled_events[]")) if hasattr(body, "getlist") else [],
        "secret": f"whsec_{uuid.uuid4().hex}",
        "status": "enabled",
        "description": body.get("description", ""),
        "created": 1709251200,
    }
    _webhooks.append(wh)
    return wh


@router.get("/v1/webhook_endpoints")
async def list_webhooks(limit: int = 100):
    return paginate_list(_webhooks, "/v1/webhook_endpoints", limit)


@router.delete("/v1/webhook_endpoints/{webhook_id}")
async def delete_webhook(webhook_id: str):
    global _webhooks
    _webhooks = [w for w in _webhooks if w["id"] != webhook_id]
    return {"id": webhook_id, "object": "webhook_endpoint", "deleted": True}
