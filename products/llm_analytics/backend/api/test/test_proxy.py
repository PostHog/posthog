from types import SimpleNamespace
from uuid import uuid4

from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.rate_limit import LLMProxyBurstRateThrottle, LLMProxyDailyRateThrottle, LLMProxySustainedRateThrottle

from products.llm_analytics.backend.api.proxy import LLMProxyViewSet
from products.llm_analytics.backend.models.provider_keys import LLMProviderKey

ALL_THROTTLES = (LLMProxyBurstRateThrottle, LLMProxySustainedRateThrottle, LLMProxyDailyRateThrottle)


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
        self.viewset.request = SimpleNamespace(data=data, user=self.user)

    @parameterized.expand(
        [
            ("no_provider_key", None, "openai", None, True),
            ("invalid_provider_key_id", str(uuid4()), "openai", None, True),
            ("provider_key_without_api_key", "generated", "openai", {}, True),
            (
                "provider_mismatch_key_anthropic_request_openai",
                "generated",
                "anthropic",
                {"api_key": "sk-ant-key"},
                True,
            ),
            ("provider_mismatch_key_openai_request_anthropic", "generated", "openai", {"api_key": "sk-key"}, True),
            ("valid_matching_provider_key", "generated", "openai", {"api_key": "sk-test-key"}, False),
            ("user_without_team", "generated", "openai", {"api_key": "sk-test-key"}, True),
        ]
    )
    def test_completion_throttle_behavior(
        self, _name: str, provider_key_id, key_provider, encrypted_config, expect_throttled: bool
    ) -> None:
        if _name == "user_without_team":
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

        request_provider = "anthropic" if _name == "provider_mismatch_key_openai_request_anthropic" else "openai"
        self._set_request("completion", self._completion_payload(provider_key_id, provider=request_provider))

        throttles = self.viewset.get_throttles()

        if expect_throttled:
            assert len(throttles) == len(ALL_THROTTLES)
            for throttle, expected_cls in zip(throttles, ALL_THROTTLES):
                assert isinstance(throttle, expected_cls)
        else:
            assert throttles == []

    def test_models_endpoint_is_never_throttled(self) -> None:
        self._set_request("models", {})
        assert self.viewset.get_throttles() == []
