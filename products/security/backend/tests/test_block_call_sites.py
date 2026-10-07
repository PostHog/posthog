import time
from datetime import timedelta

import pytest
import time_machine
from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.conf import settings
from django.test import RequestFactory
from django.utils import timezone

from parameterized import parameterized
from prometheus_client import REGISTRY
from social_core.exceptions import AuthFailed

from posthog.api.authentication import social_access_rules_allow
from posthog.api.signup import (
    process_social_domain_jit_provisioning_signup,
    process_social_invite_signup,
    signup_refused,
)
from posthog.models import Organization, User
from posthog.models.oauth import OAuthAccessToken, OAuthApplication
from posthog.models.organization_domain import OrganizationDomain
from posthog.models.organization_invite import OrganizationInvite
from posthog.models.personal_api_key import PersonalAPIKey
from posthog.models.utils import generate_random_token_personal, hash_key_value

from products.security.backend.logic import snapshot
from products.security.backend.tests.helpers import block_rule, enforcing, seed_rules


def _count(surface: str, call_site: str, target_type: str) -> float:
    return (
        REGISTRY.get_sample_value(
            "posthog_security_access_would_block_total",
            {"surface": surface, "call_site": call_site, "target_type": target_type},
        )
        or 0.0
    )


class TestBlockCallSites(APIBaseTest):
    # The default test user is a posthog.com account, which no block rule may reach.
    CONFIG_EMAIL = "member@example.com"

    @parameterized.expand([("logged only", [], 201, 1), ("enforced", ["signup"], 403, 0)])
    def test_blocked_signup(self, _name: str, enforced: list[str], status: int, would_block: int) -> None:
        seed_rules(block_rule(targetType="email_domain", targetValue="throwaway.example", scope="signup"))
        before = _count("signup", "signup", "email_domain")
        self.client.logout()
        # CanCreateOrg only opens outside cloud/DEBUG when no organization exists yet;
        # setUpTestData already created one, so this test's own org must go first.
        self.organization.delete()
        with enforcing(*enforced):
            response = self.client.post(
                "/api/signup/",
                {
                    "email": "new.user@throwaway.example",
                    "password": "a-long-password-123",
                    "first_name": "New",
                    "organization_name": "Org",
                },
            )
        assert response.status_code == status, response.json()
        assert _count("signup", "signup", "email_domain") == before + would_block
        assert User.objects.filter(email="new.user@throwaway.example").exists() is (status == 201)
        if status == 403:
            assert response.json()["code"] == "access_blocked"

    @parameterized.expand([("logged only", [], 200, 1), ("enforced", ["app"], 403, 0)])
    def test_blocked_login(self, _name: str, enforced: list[str], status: int, would_block: int) -> None:
        user = User.objects.create_and_join(self.organization, "blocked.login@example.com", "a-long-password-123")
        seed_rules(block_rule(targetType="user_uuid", targetValue=str(user.uuid)))
        before = _count("app", "login", "user_uuid")
        self.client.logout()
        with enforcing(*enforced):
            response = self.client.post(
                "/api/login", {"email": "blocked.login@example.com", "password": "a-long-password-123"}
            )
        assert response.status_code == status, response.json()
        assert _count("app", "login", "user_uuid") == before + would_block
        assert ("_auth_user_id" in self.client.session) is (status == 200)
        if status == 403:
            assert response.json()["code"] == "access_blocked"

    @parameterized.expand([("logged only", [], 201, 1), ("enforced", ["signup"], 403, 0)])
    def test_blocked_existing_user_accepting_an_invite(
        self, _name: str, enforced: list[str], status: int, would_block: int
    ) -> None:
        # self.user (already logged in) is created with CONFIG_EMAIL, so this exercises the
        # branch InviteSignupSerializer.create takes when the invite acceptor already has an account.
        seed_rules(block_rule(targetType="email", targetValue=self.CONFIG_EMAIL))
        new_org = Organization.objects.create(name="Other Org")
        invite = OrganizationInvite.objects.create(target_email=self.user.email, organization=new_org)

        before = _count("signup", "invite_signup", "email")
        with enforcing(*enforced), self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(f"/api/signup/{invite.id}/")
        assert response.status_code == status, response.json()
        assert _count("signup", "invite_signup", "email") == before + would_block
        assert self.user.organizations.filter(id=new_org.id).exists() is (status == 201)

    @parameterized.expand([("logged only", [], False), ("enforced", ["app"], True)])
    def test_blocked_sso_login(self, _name: str, enforced: list[str], refused: bool) -> None:
        user = User.objects.create_and_join(self.organization, "blocked.sso@example.com", None)
        seed_rules(block_rule(targetValue="blocked.sso@example.com"))
        before = _count("app", "sso_login", "email")
        strategy = MagicMock(request=RequestFactory().get("/complete/google-oauth2/"))

        with enforcing(*enforced):
            if refused:
                with pytest.raises(AuthFailed, match="access_blocked"):
                    social_access_rules_allow(strategy, MagicMock(), user=user)
            else:
                social_access_rules_allow(strategy, MagicMock(), user=user)

        assert _count("app", "sso_login", "email") == before + (0 if refused else 1)
        # The step does nothing unless the pipeline runs it before the session starts.
        pipeline = list(settings.SOCIAL_AUTH_PIPELINE)
        assert pipeline.index("posthog.api.authentication.social_access_rules_allow") < pipeline.index(
            "posthog.api.signup.social_create_user"
        )

    @parameterized.expand(
        [
            ("logged only", [], False, 200, 1),
            ("enforced", ["app"], False, 401, 0),
            ("enforced, but staff are impersonating", ["app"], True, 200, 1),
        ]
    )
    def test_blocked_session(
        self, _name: str, enforced: list[str], impersonated: bool, status: int, would_block: int
    ) -> None:
        seed_rules(block_rule(targetType="email", targetValue=self.user.email.lower()))
        before = _count("app", "session", "email")
        with (
            enforcing(*enforced),
            patch("posthog.auth.is_impersonated_session", return_value=impersonated),
        ):
            response = self.client.get("/api/users/@me/")
        assert response.status_code == status, response.json()
        assert _count("app", "session", "email") == before + would_block
        if status == 401:
            assert response.json()["code"] == "access_blocked"

    def _bearer(self, kind: str) -> str:
        if kind == "personal_api_key":
            key = generate_random_token_personal()
            PersonalAPIKey.objects.create(label="Test", user=self.user, secure_value=hash_key_value(key), scopes=["*"])
            return key
        application = OAuthApplication.objects.create(
            name="Test app",
            client_id="test_client_id",
            client_secret="test_client_secret",
            client_type=OAuthApplication.CLIENT_CONFIDENTIAL,
            authorization_grant_type=OAuthApplication.GRANT_AUTHORIZATION_CODE,
            redirect_uris="https://example.com/callback",
            user=self.user,
            hash_client_secret=True,
            algorithm="RS256",
        )
        token = f"pha_{generate_random_token_personal()}"
        OAuthAccessToken.objects.create(
            user=self.user,
            application=application,
            token=token,
            scope="*",
            expires=timezone.now() + timedelta(hours=1),
        )
        return token

    @parameterized.expand(
        [
            ("personal API key, logged only", "personal_api_key", [], 200, 1),
            ("personal API key, enforced", "personal_api_key", ["app"], 401, 0),
            ("OAuth token, logged only", "oauth_token", [], 200, 1),
            ("OAuth token, enforced", "oauth_token", ["app"], 401, 0),
        ]
    )
    def test_blocked_bearer_credential(
        self, _name: str, kind: str, enforced: list[str], status: int, would_block: int
    ) -> None:
        # DRF stops at the first authenticator that succeeds, and the bearer ones run before the
        # session one, so a check on the session alone leaves an existing key or token working.
        seed_rules(block_rule(targetType="email", targetValue=self.user.email.lower()))
        token = self._bearer(kind)
        self.client.logout()
        before = _count("app", kind, "email")

        with enforcing(*enforced):
            response = self.client.get("/api/users/@me/", headers={"authorization": f"Bearer {token}"})

        assert response.status_code == status, response.json()
        assert _count("app", kind, "email") == before + would_block
        if status == 401:
            assert response.json()["code"] == "access_blocked"

    def test_session_check_reads_the_memo_not_redis(self) -> None:
        # The session check runs on every authenticated request, so a Redis read here would be
        # a latency incident on the whole app.
        seed_rules(block_rule(targetValue="someone.else@example.com"))
        with enforcing("app"), time_machine.travel(time.time(), tick=False):
            assert self.client.get("/api/users/@me/").status_code == 200
            with patch.object(snapshot, "get_client") as redis:
                assert self.client.get("/api/users/@me/").status_code == 200
        redis.assert_not_called()

    def test_unmatched_requests_log_nothing(self) -> None:
        seed_rules(block_rule(targetValue="someone.else@example.com"))
        before = _count("app", "session", "email")
        assert self.client.get("/api/users/@me/").status_code == 200
        assert _count("app", "session", "email") == before

    def _sso_join(self, path: str, email: str, user: User | None, organization: Organization) -> None:
        strategy = MagicMock(request=RequestFactory().get("/complete/google-oauth2/"))
        if path == "invite":
            invite = OrganizationInvite.objects.create(target_email=email, organization=organization)
            process_social_invite_signup(strategy, str(invite.id), email, "Joiner", user, backend=MagicMock())
        else:
            OrganizationDomain.objects.create(
                organization=organization,
                domain="jit.example",
                verified_at=timezone.now(),
                jit_provisioning_enabled=True,
            )
            process_social_domain_jit_provisioning_signup(strategy, email, "Joiner", user, backend=MagicMock())

    @parameterized.expand(
        [
            ("invite, existing account, logged only", "invite", False, [], False),
            ("invite, existing account, enforced", "invite", False, ["signup"], True),
            ("invite, new account, enforced", "invite", True, ["signup"], True),
            ("verified domain, existing account, logged only", "jit", False, [], False),
            ("verified domain, existing account, enforced", "jit", False, ["signup"], True),
        ]
    )
    def test_blocked_sso_join(
        self, _name: str, path: str, new_account: bool, enforced: list[str], refused: bool
    ) -> None:
        # Invite and verified-domain joins over SSO never reach the signup serializers.
        email = "joiner@jit.example"
        seed_rules(block_rule(targetValue=email, scope="signup"))
        joined = Organization.objects.create(name="Joined org")
        user = None if new_account else User.objects.create_and_join(self.organization, email, None)

        with enforcing(*enforced):
            if refused:
                with pytest.raises(AuthFailed, match="access_blocked"):
                    self._sso_join(path, email, user, joined)
            else:
                self._sso_join(path, email, user, joined)

        assert joined.members.filter(email=email).exists() is not refused

    @parameterized.expand([("logged only", [], False, 1), ("enforced", ["signup"], True, 0)])
    def test_partner_signup(self, _name: str, enforced: list[str], refused: bool, would_block: int) -> None:
        # Partner provisioning (agentic, Stripe, Vercel) creates accounts outside the signup serializers.
        seed_rules(block_rule(targetType="email_domain", targetValue="throwaway.example", scope="signup"))
        before = _count("signup", "agentic_provisioning", "email_domain")

        with enforcing(*enforced):
            assert signup_refused("new.user@throwaway.example", call_site="agentic_provisioning") is refused

        assert _count("signup", "agentic_provisioning", "email_domain") == before + would_block
