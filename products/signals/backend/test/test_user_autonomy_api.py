from posthog.test.base import APIBaseTest

from parameterized import parameterized

from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.signals.backend.models import SignalUserAutonomyConfig


class TestSignalUserAutonomyScopes(APIBaseTest):
    ENDPOINT = "/api/users/@me/signal_autonomy/"

    def setUp(self) -> None:
        super().setUp()
        SignalUserAutonomyConfig.objects.create(user=self.user, autostart_priority="P1")
        self.client.logout()

    def _auth(self, scopes: list[str]) -> dict[str, str]:
        value = generate_random_token_personal()
        PersonalAPIKey.objects.create(label="key", user=self.user, secure_value=hash_key_value(value), scopes=scopes)
        return {"HTTP_AUTHORIZATION": f"Bearer {value}"}

    @parameterized.expand(
        [
            ("read key reads", "get", ["user:read"], 200),
            ("read key cannot write", "post", ["user:read"], 403),
            ("write key writes", "post", ["user:write"], 200),
            ("unrelated key cannot read", "get", ["dashboard:read"], 403),
        ]
    )
    def test_scope_follows_the_method(self, _name: str, method: str, scopes: list[str], expected: int) -> None:
        response = getattr(self.client, method)(self.ENDPOINT, {"autostart_priority": "P2"}, **self._auth(scopes))

        assert response.status_code == expected, response.json()
