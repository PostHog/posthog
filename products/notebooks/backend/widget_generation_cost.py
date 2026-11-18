from decimal import Decimal, InvalidOperation
from urllib.parse import quote

import httpx
import structlog

from posthog.llm.billing import AI_COST_MARKUP_PERCENT
from posthog.llm.gateway_client import resolve_ai_gateway_config

logger = structlog.get_logger(__name__)


def get_widget_generation_cost(request_ids: list[str | None]) -> Decimal | None:
    gateway = resolve_ai_gateway_config()
    if gateway is None or not request_ids or any(request_id is None for request_id in request_ids):
        return None

    total = Decimal(0)
    try:
        with httpx.Client(
            base_url=gateway.url.rstrip("/") + "/",
            headers={"Authorization": f"Bearer {gateway.api_key}"},
            timeout=3,
            trust_env=False,
        ) as client:
            for request_id in dict.fromkeys(request_ids):
                assert request_id is not None
                response = client.get(f"usage/{quote(request_id, safe='')}")
                response.raise_for_status()
                body = response.json()
                if not isinstance(body, dict):
                    return None
                amount = body.get("cost_usd")
                if not isinstance(amount, str):
                    return None
                cost = Decimal(amount)
                if not cost.is_finite() or cost < 0:
                    return None
                total += cost
            return (total * (1 + Decimal(str(AI_COST_MARKUP_PERCENT)))).quantize(Decimal("0.000001"))
    except (httpx.HTTPError, ValueError, InvalidOperation):
        logger.warning("notebook_widget_generation_cost_unavailable")
        return None
