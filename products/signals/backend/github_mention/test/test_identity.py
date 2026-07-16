from posthog.test.base import BaseTest

from django.utils import timezone

from posthog.models import Organization, OrganizationMembership, User
from posthog.models.user_integration import UserIntegration

from products.signals.backend.github_mention.identity import MentionIdentityStatus, resolve_commenter_identity

REPO = "acme/app"
ACCOUNT_ID = 4242


class TestResolveCommenterIdentity(BaseTest):
    def _connect_github(
        self,
        *,
        user: User,
        account_id: int = ACCOUNT_ID,
        usable: bool = True,
        covers_repo: bool = True,
    ) -> UserIntegration:
        sensitive: dict[str, str] = {}
        if usable:
            sensitive = {"user_access_token": "gho_tok", "user_refresh_token": "ghr_tok"}
        return UserIntegration.objects.create(
            user=user,
            kind="github",
            integration_id="999",
            config={"github_user": {"login": "octocat", "id": account_id}},
            sensitive_config=sensitive,
            repository_cache=[{"full_name": REPO}] if covers_repo else [{"full_name": "other/repo"}],
            repository_cache_updated_at=timezone.now(),
        )

    def test_member_with_usable_repo_covering_connection_is_eligible(self) -> None:
        self._connect_github(user=self.user)

        identity = resolve_commenter_identity(
            team=self.team, github_account_id=ACCOUNT_ID, github_login="octocat", repository=REPO
        )

        self.assertEqual(identity.status, MentionIdentityStatus.ELIGIBLE)
        self.assertEqual(identity.user, self.user)
        self.assertIsNotNone(identity.user_github_integration)

    def test_connection_not_covering_repo_is_not_eligible(self) -> None:
        self._connect_github(user=self.user, covers_repo=False)

        identity = resolve_commenter_identity(
            team=self.team, github_account_id=ACCOUNT_ID, github_login="octocat", repository=REPO
        )

        self.assertEqual(identity.status, MentionIdentityStatus.NEEDS_CONNECT)

    def test_unusable_connection_is_not_eligible(self) -> None:
        self._connect_github(user=self.user, usable=False)

        identity = resolve_commenter_identity(
            team=self.team, github_account_id=ACCOUNT_ID, github_login="octocat", repository=REPO
        )

        self.assertEqual(identity.status, MentionIdentityStatus.NEEDS_CONNECT)

    def test_matching_account_id_but_not_org_member_is_rejected(self) -> None:
        outsider_org = Organization.objects.create(name="outsider")
        outsider = User.objects.create(email="outsider@example.com", first_name="Out")
        OrganizationMembership.objects.create(organization=outsider_org, user=outsider)
        self._connect_github(user=outsider)

        identity = resolve_commenter_identity(
            team=self.team, github_account_id=ACCOUNT_ID, github_login="octocat", repository=REPO
        )

        self.assertEqual(identity.status, MentionIdentityStatus.NOT_MEMBER)

    def test_account_id_mismatch_never_yields_eligible(self) -> None:
        # A member has a real connection under account id ACCOUNT_ID. A webhook arrives with the same
        # login but a DIFFERENT account id (spoof / recreated login). Resolution must not run as them.
        self._connect_github(user=self.user, account_id=ACCOUNT_ID)

        identity = resolve_commenter_identity(
            team=self.team, github_account_id=9999, github_login="octocat", repository=REPO
        )

        self.assertNotEqual(identity.status, MentionIdentityStatus.ELIGIBLE)
