from types import SimpleNamespace
from typing import cast
from uuid import uuid4

from posthog.test.base import APIBaseTest

from parameterized import parameterized
from rest_framework.request import Request

from posthog.rate_limit import (
    LLMProxyBurstRateThrottle,
    LLMProxyBYOKBurstRateThrottle,
    LLMProxyBYOKDailyRateThrottle,
    LLMProxyBYOKSustainedRateThrottle,
    LLMProxyDailyRateThrottle,
    LLMProxySustainedRateThrottle,
)

from products.llm_analytics.backend.api.proxy import LLMProxyViewSet
from products.llm_analytics.backend.models.provider_keys import LLMProviderKey

TRIAL_THROTTLES = (LLMProxyBurstRateThrottle, LLMProxySustainedRateThrottle, LLMProxyDailyRateThrottle)
BYOK_THROTTLES = (LLMProxyBYOKBurstRateThrottle, LLMProxyBYOKSustainedRateThrottle, LLMProxyBYOKDailyRateThrottle)


class TestLLMProxyThrottles(APIBaseTest):
    def setUp(self) -> None:
        super().setUp()
        self.user.current_team = self.team
        self.viewset = LLMProxyViewSet()

    def _completion_payload(self, provider_key_id: str | None = None, provider: str = "openai") -> dict:
        payload: dict = {
            "system": "",
            "messages": [{"role": "user", "content": "hello"}],
            "model": "gpt-4.1-mini",
            "provider": provider,
        }
        if provider_key_id is not None:
            payload["provider_key_id"] = provider_key_id
        return payload

    def _set_request(self, action: str, data: dict) -> None:
        self.viewset.action = action
        self.viewset.request = cast(Request, SimpleNamespace(data=data, user=self.user))

    # Params: (provider_key_id, key_provider, encrypted_config, request_provider, has_team, expected_throttles)
    @parameterized.expand(
        [
            ("no_provider_key", None, "openai", None, "openai", True, TRIAL_THROTTLES),
            ("invalid_provider_key_id", str(uuid4()), "openai", None, "openai", True, TRIAL_THROTTLES),
            ("provider_key_without_api_key", "generated", "openai", {}, "openai", True, TRIAL_THROTTLES),
            (
                "provider_mismatch_key_anthropic_req_openai",
                "generated",
                "anthropic",
                {"api_key": "sk-ant-key"},
                "openai",
                True,
                TRIAL_THROTTLES,
            ),
            (
                "provider_mismatch_key_openai_req_anthropic",
                "generated",
                "openai",
                {"api_key": "sk-key"},
                "anthropic",
                True,
                TRIAL_THROTTLES,
            ),
            (
                "valid_matching_provider_key",
                "generated",
                "openai",
                {"api_key": "sk-test-key"},
                "openai",
                True,
                BYOK_THROTTLES,
            ),
            ("user_without_team", "generated", "openai", {"api_key": "sk-test-key"}, "openai", False, TRIAL_THROTTLES),
        ]
    )
    def test_completion_throttle_behavior(
        self,
        _name: str,
        provider_key_id,
        key_provider,
        encrypted_config,
        request_provider: str,
        has_team: bool,
        expected_throttles: tuple,
    ) -> None:
        if not has_team:
            self.user.current_team = None

        if provider_key_id == "generated":
            key = LLMProviderKey.objects.create(
                team=self.team,
                provider=key_provider,
                name="Test key",
                encrypted_config=encrypted_config,
                created_by=self.user,
            )
            provider_key_id = str(key.id)

        self._set_request("completion", self._completion_payload(provider_key_id, provider=request_provider))

        throttles = self.viewset.get_throttles()

        assert len(throttles) == len(expected_throttles)
        for throttle, expected_cls in zip(throttles, expected_throttles):
            assert isinstance(throttle, expected_cls)

    def test_models_endpoint_is_never_throttled(self) -> None:
        self._set_request("models", {})
        assert self.viewset.get_throttles() == []
