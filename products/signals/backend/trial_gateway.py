from uuid import UUID

from django.conf import settings

import httpx

from posthog.dataclasses import frozen


@frozen
class TrialGatewayCost:
    token_cost_microusd: int
    complete: bool


def fetch_trial_gateway_cost(*, environment_id: int, operation_id: UUID) -> TrialGatewayCost | None:
    url = (settings.AI_GATEWAY_URL or "").rstrip("/").removesuffix("/v1")
    if not url or not settings.AI_GATEWAY_API_KEY:
        return None
    try:
        response = httpx.get(
            f"{url}/v1/trials/{environment_id}/operations/{operation_id}/usage",
            headers={"Authorization": f"Bearer {settings.AI_GATEWAY_API_KEY}"},
            timeout=10,
            follow_redirects=False,
            trust_env=False,
        )
        response.raise_for_status()
        data = response.json()
        amount = data.get("cost_microusd")
        if type(amount) is not int or amount < 0 or type(data.get("complete")) is not bool:
            return None
        return TrialGatewayCost(token_cost_microusd=amount, complete=data["complete"])
    except (httpx.HTTPError, ValueError, TypeError, AttributeError):
        return None
