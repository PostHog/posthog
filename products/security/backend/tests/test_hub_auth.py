import time

from django.test import SimpleTestCase, override_settings

import jwt as pyjwt
from parameterized import parameterized

from products.security.backend.logic.hub_auth import claims_allow, mint_rules_token


@override_settings(SECURITY_HUB_REGION="us", SECURITY_HUB_OUTBOUND_JWT_SECRETS=["new", "old"])
class TestHubAuth(SimpleTestCase):
    def test_rules_token_claims(self) -> None:
        claims = pyjwt.decode(mint_rules_token(), "new", algorithms=["HS256"], audience="posthog:security_hub:rules")
        assert claims["region"] == "us"
        assert claims["op"] == "rules:read"
        assert 0 < claims["exp"] - claims["iat"] <= 60

    @parameterized.expand(
        [
            ("valid", {"region": "us", "op": "subject:resolve", "iat": 100, "exp": 160}, True),
            ("wrong op", {"region": "us", "op": "rules:sync_now", "iat": 100, "exp": 160}, False),
            ("wrong region", {"region": "eu", "op": "subject:resolve", "iat": 100, "exp": 160}, False),
            ("too long", {"region": "us", "op": "subject:resolve", "iat": 100, "exp": 161}, False),
            ("no iat", {"region": "us", "op": "subject:resolve", "exp": 160}, False),
            ("string iat", {"region": "us", "op": "subject:resolve", "iat": "100", "exp": 160}, False),
        ]
    )
    def test_claims_allow(self, _name: str, claims: dict, expected: bool) -> None:
        assert claims_allow(claims, "subject:resolve") is expected

    def test_claims_allow_rejects_missing_claims(self) -> None:
        assert claims_allow(None, "subject:resolve") is False
        assert (
            claims_allow(
                {"region": "us", "op": "subject:resolve", "iat": int(time.time()), "exp": True}, "subject:resolve"
            )
            is False
        )
