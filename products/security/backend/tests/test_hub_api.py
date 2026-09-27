import time
from typing import Any

from posthog.test.base import BaseTest
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import override_settings

import jwt as pyjwt
from parameterized import parameterized
from rest_framework.test import APIClient

from posthog.helpers.two_factor_session import (
    add_code_based_verification_bypass,
    set_code_based_verification_global_disable,
)
from posthog.models import User

SECRET = "in-us"
SETTINGS = {"SECURITY_HUB_REGION": "us", "SECURITY_HUB_INBOUND_JWT_SECRETS": [SECRET]}


def token(op: str, key: str = SECRET, **overrides: object) -> str:
    now = int(time.time())
    claims = {
        "aud": "posthog:security_hub:internal",
        "region": "us",
        "op": op,
        "iat": now,
        "exp": now + 60,
        **overrides,
    }
    return pyjwt.encode(claims, key, algorithm="HS256")


@override_settings(**SETTINGS)
class TestHubApi(BaseTest):
    # The default test user is a posthog.com account, which would make the org protected.
    CONFIG_EMAIL = "member@example.com"

    def setUp(self) -> None:
        super().setUp()
        cache.clear()
        self.client = APIClient()

    def post(self, path: str, body: dict, op: str | None, **claims: Any):
        headers: dict[str, Any] = {"HTTP_AUTHORIZATION": f"Bearer {token(op, **claims)}"} if op else {}
        return self.client.post(f"/api/security/{path}/", body, format="json", **headers)

    def test_resolve(self) -> None:
        user = User.objects.create_and_join(self.organization, "farm.bot+1@example.com", "password1234")
        response = self.post("resolve", {"query": "farm.bot+1@example.com"}, "subject:resolve")
        assert response.status_code == 200
        assert response.json() == {
            "kind": "user",
            "user": {"uuid": str(user.uuid), "email": "farm.bot+1@example.com", "is_active": True},
            "organization_ids": [str(self.organization.id)],
            "organization": None,
        }

    def test_resolve_organization(self) -> None:
        response = self.post("resolve", {"query": str(self.organization.id)}, "subject:resolve")
        assert response.status_code == 200
        assert response.json() == {
            "kind": "organization",
            "user": None,
            "organization_ids": [str(self.organization.id)],
            "organization": {"id": str(self.organization.id), "exists": True},
        }

    def test_counts_and_membership(self) -> None:
        User.objects.create_and_join(self.organization, "a@throwaway.example", "password1234")
        counted = self.post(
            "count-accounts", {"target_type": "email_domain", "target_value": "throwaway.example"}, "accounts:count"
        )
        assert counted.json() == {"count": 1, "capped": False}
        members = self.post("org-member-count", {"organization_id": str(self.organization.id)}, "org:member_count")
        assert members.json()["exists"] is True
        membership = self.post(
            "posthog-membership", {"organization_id": str(self.organization.id)}, "posthog_membership:check"
        )
        assert membership.json() == {"has_posthog_account": False}

    @parameterized.expand(
        [
            (
                "both targets",
                {
                    "user_uuid": "2222abcd-2222-4222-8222-22222222abcd",
                    "organization_id": "1111aaaa-1111-4111-8111-11111111aaaa",
                },
            ),
            ("no target", {}),
            ("bad uuid", {"user_uuid": "nope"}),
        ]
    )
    def test_membership_needs_exactly_one_valid_target(self, _name: str, body: dict) -> None:
        assert self.post("posthog-membership", body, "posthog_membership:check").status_code == 400

    def test_count_refuses_other_types(self) -> None:
        response = self.post("count-accounts", {"target_type": "ip", "target_value": "1.2.3.4"}, "accounts:count")
        assert response.status_code == 400

    @patch("products.security.backend.presentation.hub_api.start_sync_now")
    def test_sync_now(self, start: MagicMock) -> None:
        assert self.post("sync-now", {}, "rules:sync_now").status_code == 202
        start.assert_called_once_with()

    @patch("products.security.backend.presentation.hub_api.start_sync_now", side_effect=RuntimeError("temporal down"))
    def test_sync_now_answers_503_when_temporal_is_unreachable(self, start: MagicMock) -> None:
        assert self.post("sync-now", {}, "rules:sync_now").status_code == 503

    def test_mfa_export(self) -> None:
        add_code_based_verification_bypass("Bypass@Example.com")
        set_code_based_verification_global_disable(
            reason="email outage", ttl_seconds=3600, disabled_by="ops@posthog.com"
        )
        body = self.post("mfa-bypass-export", {}, "mfa_bypass:export").json()
        assert body["emails"] == ["bypass@example.com"]
        assert body["global"]["reason"] == "email outage"
        assert body["global"]["actor"] == "ops@posthog.com"
        assert body["global"]["expires_at"].endswith("Z")

    def test_mfa_export_without_a_global_switch(self) -> None:
        assert self.post("mfa-bypass-export", {}, "mfa_bypass:export").json() == {"emails": [], "global": None}

    @parameterized.expand(
        [
            ("no token", None, {}, 401),
            ("wrong key", "subject:resolve", {"key": "other"}, 401),
            ("wrong audience", "subject:resolve", {"aud": "posthog:security_hub:rules"}, 401),
            ("expired", "subject:resolve", {"iat": 100, "exp": 160}, 401),
            ("wrong op", "rules:sync_now", {}, 403),
            ("wrong region", "subject:resolve", {"region": "eu"}, 403),
            ("too long", "subject:resolve", {"exp": int(time.time()) + 3600}, 403),
        ]
    )
    def test_auth_refusals(self, _name: str, op: str | None, claims: dict, expected: int) -> None:
        assert self.post("resolve", {"query": "x@example.com"}, op, **claims).status_code == expected

    @override_settings(SECURITY_HUB_INBOUND_JWT_SECRETS=[])
    def test_unprovisioned_secret_refuses_everything(self) -> None:
        assert self.post("resolve", {"query": "x@example.com"}, "subject:resolve").status_code == 401

    def test_get_is_not_allowed(self) -> None:
        response = self.client.get("/api/security/resolve/", HTTP_AUTHORIZATION=f"Bearer {token('subject:resolve')}")
        assert response.status_code == 405

    def test_global_throttle(self) -> None:
        # One budget for every hub route together: alternate between two different
        # routes so a throttle that was accidentally scoped per view would leave each
        # one under its own limit and this test would pass for the wrong reason.
        requests = [
            ("resolve", {"query": "x@example.com"}, "subject:resolve"),
            ("posthog-membership", {"organization_id": str(self.organization.id)}, "posthog_membership:check"),
        ]
        codes = [self.post(*requests[i % 2]).status_code for i in range(101)]
        assert codes[:100] == [200] * 100
        assert codes[100] == 429

    @parameterized.expand([("no token", None), ("wrong op", "rules:sync_now")])
    def test_refused_requests_do_not_consume_throttle_budget(self, _name: str, op: str | None) -> None:
        for _ in range(150):
            assert self.post("resolve", {"query": "x@example.com"}, op).status_code in (401, 403)
        assert self.post("resolve", {"query": "x@example.com"}, "subject:resolve").status_code == 200
