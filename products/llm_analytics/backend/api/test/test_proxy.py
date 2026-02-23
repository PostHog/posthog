from types import SimpleNamespace
from uuid import uuid4

from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.rate_limit import LLMProxyBurstRateThrottle, LLMProxyDailyRateThrottle, LLMProxySustainedRateThrottle

from products.llm_analytics.backend.api.proxy import LLMProxyViewSet
from products.llm_analytics.backend.models.provider_keys import LLMProviderKey


class TestLLMProxyViewSet(APIBaseTest):
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

    @parameterized.expand(
        [
            ("no_provider_key", None, "openai", None, 3),
            ("invalid_provider_key_id", str(uuid4()), "openai", None, 3),
            ("provider_key_without_api_key", "generated", "openai", {}, 3),
            ("provider_mismatch", "generated", "anthropic", {"api_key": "sk-ant-test-key"}, 3),
            ("valid_provider_key", "generated", "openai", {"api_key": "sk-test-key"}, 0),
        ]
    )
    def test_completion_throttle_behavior(
        self, _name, provider_key_id, key_provider, encrypted_config, expected_throttle_count
    ) -> None:
        if provider_key_id == "generated":
            key = LLMProviderKey.objects.create(
                team=self.team,
                provider=key_provider,
                name="Test key",
                encrypted_config=encrypted_config,
                created_by=self.user,
            )
            provider_key_id = str(key.id)

        self.viewset.action = "completion"
        self.viewset.request = SimpleNamespace(
            data=self._completion_payload(provider_key_id, provider="openai"), user=self.user
        )

        throttles = self.viewset.get_throttles()

        self.assertEqual(len(throttles), expected_throttle_count)
        if expected_throttle_count == 3:
            self.assertIsInstance(throttles[0], LLMProxyBurstRateThrottle)
            self.assertIsInstance(throttles[1], LLMProxySustainedRateThrottle)
            self.assertIsInstance(throttles[2], LLMProxyDailyRateThrottle)

    def test_models_endpoint_is_never_throttled(self) -> None:
        self.viewset.action = "models"
        self.viewset.request = SimpleNamespace(data={}, user=self.user)

        self.assertEqual(self.viewset.get_throttles(), [])
