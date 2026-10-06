from posthog.test.base import APIBaseTest

from prometheus_client import REGISTRY

from posthog.models import Organization, User
from posthog.models.organization_invite import OrganizationInvite

from products.security.backend.tests.helpers import block_rule, seed_rules


def _count(surface: str, call_site: str, target_type: str) -> float:
    return (
        REGISTRY.get_sample_value(
            "posthog_security_access_would_block_total",
            {"surface": surface, "call_site": call_site, "target_type": target_type},
        )
        or 0.0
    )


class TestShadowCallSites(APIBaseTest):
    # The default test user is a posthog.com account, which no block rule may reach.
    CONFIG_EMAIL = "member@example.com"

    def test_blocked_signup_is_logged_and_still_succeeds(self) -> None:
        seed_rules(block_rule(targetType="email_domain", targetValue="throwaway.example", scope="signup"))
        before = _count("signup", "signup", "email_domain")
        self.client.logout()
        # CanCreateOrg only opens outside cloud/DEBUG when no organization exists yet;
        # setUpTestData already created one, so this test's own org must go first.
        self.organization.delete()
        response = self.client.post(
            "/api/signup/",
            {
                "email": "new.user@throwaway.example",
                "password": "a-long-password-123",
                "first_name": "New",
                "organization_name": "Org",
            },
        )
        assert response.status_code == 201, response.json()
        assert _count("signup", "signup", "email_domain") == before + 1

    def test_blocked_login_is_logged_and_still_succeeds(self) -> None:
        user = User.objects.create_and_join(self.organization, "blocked.login@example.com", "a-long-password-123")
        seed_rules(block_rule(targetType="user_uuid", targetValue=str(user.uuid)))
        before = _count("app", "login", "user_uuid")
        self.client.logout()
        response = self.client.post(
            "/api/login", {"email": "blocked.login@example.com", "password": "a-long-password-123"}
        )
        assert response.status_code == 200, response.json()
        assert _count("app", "login", "user_uuid") == before + 1

    def test_blocked_existing_user_accepting_an_invite_is_logged_and_still_succeeds(self) -> None:
        # self.user (already logged in) is created with CONFIG_EMAIL, so this exercises the
        # branch InviteSignupSerializer.create takes when the invite acceptor already has an account.
        seed_rules(block_rule(targetType="email", targetValue=self.CONFIG_EMAIL))
        new_org = Organization.objects.create(name="Other Org")
        invite = OrganizationInvite.objects.create(target_email=self.user.email, organization=new_org)

        before = _count("signup", "invite_signup", "email")
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(f"/api/signup/{invite.id}/")
        assert response.status_code == 201, response.json()
        assert _count("signup", "invite_signup", "email") == before + 1

    def test_blocked_session_is_logged_and_still_served(self) -> None:
        seed_rules(block_rule(targetType="email", targetValue=self.user.email.lower()))
        before = _count("app", "session", "email")
        response = self.client.get("/api/users/@me/")
        assert response.status_code == 200
        assert _count("app", "session", "email") == before + 1

    def test_unmatched_requests_log_nothing(self) -> None:
        seed_rules(block_rule(targetValue="someone.else@example.com"))
        before = _count("app", "session", "email")
        assert self.client.get("/api/users/@me/").status_code == 200
        assert _count("app", "session", "email") == before
