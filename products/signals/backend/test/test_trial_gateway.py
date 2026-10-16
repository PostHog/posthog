from uuid import uuid4

from unittest.mock import patch

from django.test import override_settings

import httpx

from products.signals.backend.trial_gateway import TrialGatewayCost, fetch_trial_gateway_cost


@override_settings(AI_GATEWAY_URL="http://gateway:8080/v1", AI_GATEWAY_API_KEY="test-key")
def test_trial_gateway_usage_ignores_environment_proxies() -> None:
    operation_id = uuid4()
    url = f"http://gateway:8080/v1/trials/1/operations/{operation_id}/usage"
    with patch("products.signals.backend.trial_gateway.httpx.get") as get:
        get.return_value = httpx.Response(
            200, json={"cost_microusd": 1_000, "complete": True}, request=httpx.Request("GET", url)
        )
        cost = fetch_trial_gateway_cost(environment_id=1, operation_id=operation_id)

    assert cost == TrialGatewayCost(token_cost_microusd=1_000, complete=True)
    get.assert_called_once_with(
        url,
        headers={"Authorization": "Bearer test-key"},
        timeout=10,
        follow_redirects=False,
        trust_env=False,
    )
